import os
import re
import json
import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Literal, Union

from pydantic import BaseModel, Field, field_validator
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

from app.config import Config
from app.schemas.recommendation import StructuredRecommendation, IndicatorItem

logger = logging.getLogger("fraud_agent.llm_provider")


# ── Robust JSON Extraction Helper ────────────────────────────────────────────

def extract_json_from_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """Robustly extracts JSON object from LLM response text."""
    if not raw_text or not raw_text.strip():
        return None

    cleaned = raw_text.strip()

    # 1. Strip markdown code fences if present
    fence_pattern = r"^```(?:json)?\s*([\s\S]*?)\s*```$"
    match = re.search(fence_pattern, cleaned, re.MULTILINE)
    if match:
        cleaned = match.group(1).strip()

    # 2. Direct JSON parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 3. Search for outermost JSON object brackets { ... }
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = cleaned[start_idx : end_idx + 1]
        try:
            return json.loads(candidate)
        except Exception as e:
            logger.warning(f"Extracted bracket candidate could not be parsed as JSON: {e}")

    return None

# Backwards compatibility alias
extract_json_from_llm_response = extract_json_from_response


# ── Pydantic Structured Output Models & Validation ───────────────────────────

class IndicatorItemModel(BaseModel):
    statement: str = Field(
        description="Clear factual risk statement or mitigating signal grounded in evidence"
    )
    evidence_references: List[str] = Field(
        default_factory=list,
        description="List of evidence IDs cited from collected forensic evidence"
    )


VALID_ASSESSMENTS = Literal["SUSPICIOUS", "NOT_SUBSTANTIATED", "INCONCLUSIVE"]
VALID_RECOMMENDATIONS = Literal[
    "NO_ACTION", "MONITOR", "REQUEST_VERIFICATION", "SEND_NOTIFICATION",
    "TEMPORARY_RESTRICTION", "HOLD_TRANSACTION", "BLOCK_TRANSACTION",
    "BLOCK_USER", "BLOCK_MERCHANT", "ESCALATE", "UNLOCK_USER"
]
VALID_CONFIDENCES = Literal["HIGH", "MEDIUM", "LOW"]


class LLMInvestigationOutput(BaseModel):
    assessment: VALID_ASSESSMENTS = Field(
        ...,
        description="Forensic investigation assessment. Must be SUSPICIOUS, NOT_SUBSTANTIATED, or INCONCLUSIVE."
    )
    recommendation: VALID_RECOMMENDATIONS = Field(
        ...,
        description="Authorized mitigation action proposal. Must be one of the approved company actions."
    )
    explanation: str = Field(
        ...,
        min_length=20,
        description="Detailed professional reasoning explaining findings, citing evidence and risk levels (minimum 25 words)."
    )
    confidence_label: VALID_CONFIDENCES = Field(
        default="MEDIUM",
        description="Confidence level in the assessment (HIGH, MEDIUM, LOW)."
    )
    risk_indicators: List[IndicatorItemModel] = Field(
        default_factory=list,
        description="List of factual risk indicators detected from evidence."
    )
    counter_signals: List[IndicatorItemModel] = Field(
        default_factory=list,
        description="List of mitigating factors or positive compliance signals."
    )

    @field_validator("explanation")
    @classmethod
    def validate_explanation_substantive(cls, v: str) -> str:
        cleaned = v.strip()
        words = cleaned.split()
        if len(words) < 5:
            raise ValueError("Explanation is too brief; must provide substantive forensic rationale.")
        return cleaned


# ── Base LLM Provider (LangChain Native) ─────────────────────────────────────

class BaseLLMProvider(ABC):
    """Abstract interface for LangChain-native LLM reasoning providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    def get_chat_model(self) -> BaseChatModel:
        """Returns the configured LangChain BaseChatModel instance."""
        pass

    def generate(self, prompt: str, system_prompt: Optional[str] = None, json_mode: bool = True) -> str:
        """Generates raw text completion from the LLM via LangChain BaseChatModel."""
        model = self.get_chat_model()
        messages: List[BaseMessage] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))

        user_content = prompt
        if json_mode and "json" not in prompt.lower():
            user_content = f"{prompt}\n\nIMPORTANT: Respond ONLY in valid JSON format."
        messages.append(HumanMessage(content=user_content))

        t0 = time.time()
        logger.info(f"[{self.provider_name.upper()}] Invoking model {self.model_name}...")
        resp = model.invoke(messages)
        elapsed = round(time.time() - t0, 2)
        logger.info(f"[{self.provider_name.upper()}] Completed in {elapsed}s")

        content = resp.content
        if isinstance(content, list):
            return "".join([b.get("text", "") if isinstance(b, dict) else str(b) for b in content])
        return str(content)

    def generate_structured(self, prompt: str, system_prompt: Optional[str] = None) -> LLMInvestigationOutput:
        """
        Executes structured reasoning with strict Pydantic validation via LangChain.
        Uses .with_structured_output(LLMInvestigationOutput) with parser fallback.
        """
        model = self.get_chat_model()
        messages: List[BaseMessage] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        # 1. Primary path: Native with_structured_output
        try:
            structured_llm = model.with_structured_output(LLMInvestigationOutput)
            result = structured_llm.invoke(messages)
            if isinstance(result, LLMInvestigationOutput):
                return result
            elif isinstance(result, dict):
                return LLMInvestigationOutput.model_validate(result)
        except Exception as e:
            logger.warning(f"Native with_structured_output failed on {self.provider_name} ({e}). Retrying with Pydantic parser.")

        # 2. Fallback path: PydanticOutputParser with augmented prompt
        parser = PydanticOutputParser(pydantic_object=LLMInvestigationOutput)
        format_instructions = parser.get_format_instructions()
        augmented_prompt = f"{prompt}\n\n{format_instructions}"

        aug_messages: List[BaseMessage] = []
        if system_prompt:
            aug_messages.append(SystemMessage(content=system_prompt))
        aug_messages.append(HumanMessage(content=augmented_prompt))

        raw_res = model.invoke(aug_messages)
        raw_text = raw_res.content
        if isinstance(raw_text, list):
            raw_text = "".join([b.get("text", "") if isinstance(b, dict) else str(b) for b in raw_text])
        raw_text = str(raw_text)

        parsed_dict = extract_json_from_response(raw_text)
        if parsed_dict:
            return LLMInvestigationOutput.model_validate(parsed_dict)
        return parser.parse(raw_text)

    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        """Returns readiness / operational status of the provider."""
        pass


# ── Concrete Providers ───────────────────────────────────────────────────────

class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider via LangChain ChatGoogleGenerativeAI."""

    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self.model = Config.GEMINI_MODEL or "gemini-3.1-flash-lite"
        self.timeout = float(Config.LLM_TIMEOUT or 60)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self.model

    def get_chat_model(self) -> BaseChatModel:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured in environment.")
        return ChatGoogleGenerativeAI(
            model=self.model,
            google_api_key=self.api_key,
            temperature=0.2,
            timeout=self.timeout
        )

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "message": "GEMINI_API_KEY is missing"}
        return {"status": "CONFIGURED", "provider": "gemini", "model": self.model}


class MistralProvider(BaseLLMProvider):
    """
    Mistral LLM Provider via LangChain.
    Supports either:
    1. Local/On-prem Mistral via LangChain ChatOllama (e.g. mistral-small:24b or mistral:latest)
    2. Mistral Cloud API via ChatMistralAI (if MISTRAL_API_KEY is set)
    """

    def __init__(self):
        raw_url = Config.LLM_API_URL or "http://122.163.121.176:3041/api/generate"
        clean_url = re.sub(r"/api/(?:generate|chat)/?$", "", raw_url.strip())
        self.base_url = clean_url
        self.model = Config.LLM_MODEL or "mistral-small:24b"
        self.timeout = float(Config.LLM_TIMEOUT or 180)
        self.mistral_api_key = getattr(Config, "MISTRAL_API_KEY", os.getenv("MISTRAL_API_KEY", ""))

    @property
    def provider_name(self) -> str:
        return "mistral"

    @property
    def model_name(self) -> str:
        return self.model

    def get_chat_model(self) -> BaseChatModel:
        if self.mistral_api_key:
            try:
                from langchain_mistralai import ChatMistralAI
                return ChatMistralAI(
                    model=self.model,
                    api_key=self.mistral_api_key,
                    temperature=0.2,
                    timeout=self.timeout
                )
            except Exception as e:
                logger.warning(f"Could not load ChatMistralAI ({e}). Falling back to ChatOllama.")

        return ChatOllama(
            base_url=self.base_url,
            model=self.model,
            temperature=0.2,
            timeout=self.timeout
        )

    def check_health(self) -> Dict[str, Any]:
        return {
            "status": "CONFIGURED",
            "provider": "mistral",
            "model": self.model,
            "endpoint": self.base_url
        }


class CustomLocalLLMProvider(MistralProvider):
    """Backward-compatible alias for local / on-prem Mistral provider."""
    @property
    def provider_name(self) -> str:
        return "custom"


class OpenAIProvider(BaseLLMProvider):
    """OpenAI ChatGPT / GPT-4o provider via LangChain ChatOpenAI."""

    def __init__(self):
        self.api_key = Config.OPENAI_API_KEY
        self.model = Config.OPENAI_MODEL or "gpt-4o-mini"
        self.base_url = Config.OPENAI_BASE_URL.strip() if Config.OPENAI_BASE_URL else None
        self.timeout = float(Config.LLM_TIMEOUT or 60)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self.model

    def get_chat_model(self) -> BaseChatModel:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not configured in environment.")
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "api_key": self.api_key,
            "temperature": 0.2,
            "timeout": self.timeout
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return ChatOpenAI(**kwargs)

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "message": "OPENAI_API_KEY is missing"}
        return {"status": "CONFIGURED", "provider": "openai", "model": self.model}


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude LLM provider via LangChain ChatAnthropic."""

    def __init__(self):
        self.api_key = Config.ANTHROPIC_API_KEY
        self.model = Config.ANTHROPIC_MODEL or "claude-3-5-sonnet-20241022"
        self.timeout = float(Config.LLM_TIMEOUT or 60)

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def model_name(self) -> str:
        return self.model

    def get_chat_model(self) -> BaseChatModel:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured in environment.")
        return ChatAnthropic(
            model=self.model,
            api_key=self.api_key,
            temperature=0.2,
            timeout=self.timeout
        )

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "message": "ANTHROPIC_API_KEY is missing"}
        return {"status": "CONFIGURED", "provider": "claude", "model": self.model}


class AzureOpenAIProvider(BaseLLMProvider):
    """Azure OpenAI provider via LangChain AzureChatOpenAI."""

    def __init__(self):
        self.api_key = Config.AZURE_OPENAI_API_KEY
        self.endpoint = Config.AZURE_OPENAI_ENDPOINT.rstrip('/') if Config.AZURE_OPENAI_ENDPOINT else ""
        self.deployment = Config.AZURE_OPENAI_DEPLOYMENT or "gpt-4o"
        self.api_version = Config.AZURE_OPENAI_API_VERSION or "2024-02-01"
        self.model = self.deployment
        self.timeout = float(Config.LLM_TIMEOUT or 60)

    @property
    def provider_name(self) -> str:
        return "azure_openai"

    @property
    def model_name(self) -> str:
        return self.model

    def get_chat_model(self) -> BaseChatModel:
        if not self.api_key or not self.endpoint:
            raise ValueError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be configured.")
        return AzureChatOpenAI(
            azure_deployment=self.deployment,
            api_version=self.api_version,
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            temperature=0.2,
            timeout=self.timeout
        )

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key or not self.endpoint:
            return {"status": "NOT_CONFIGURED", "message": "Azure OpenAI credentials missing"}
        return {"status": "CONFIGURED", "provider": "azure_openai", "model": self.model}


# ── Provider Factory ─────────────────────────────────────────────────────────

class LLMProviderFactory:
    """Factory to instantiate and manage LangChain LLM reasoning providers."""

    @staticmethod
    def get_provider(provider_type: Optional[str] = None) -> BaseLLMProvider:
        active = (provider_type or Config.LLM_PROVIDER or "gemini").lower().strip()

        if active == "gemini":
            return GeminiProvider()
        elif active in ["mistral", "custom", "ollama", "local"]:
            return MistralProvider()
        elif active == "openai":
            return OpenAIProvider()
        elif active == "claude":
            return ClaudeProvider()
        elif active == "azure_openai":
            return AzureOpenAIProvider()
        else:
            logger.warning(f"Unknown provider '{active}', defaulting to GeminiProvider.")
            return GeminiProvider()

    @staticmethod
    def get_fallback_provider() -> BaseLLMProvider:
        """Returns the mandatory secondary fallback LLM: Mistral."""
        return MistralProvider()


# ── LLM Reasoning Service ────────────────────────────────────────────────────

class LLMReasoningService:
    """
    High-level service orchestrating structured investigation reasoning via LangChain.
    Policy:
      - Primary LLM: Gemini
      - Fallback LLM: Mistral
      - Zero mock fallbacks: If both real LLMs fail, raises an explicit exception.
    """

    SYSTEM_PROMPT = """You are Agent 34, an autonomous forensic fraud investigator for e-commerce, banking, and payment operations.
Your job is to analyze forensic evidence (user profile, transaction details, payments, dispute/chargeback history, and multi-hop graph networks) alongside relevant company policies.

CRITICAL REQUIREMENTS:
1. Ground every risk indicator and counter signal strictly in the provided evidence. Cite valid evidence IDs.
2. Never hallucinate facts or missing data.
3. You must output structured forensic findings matching the schema: assessment, recommendation, explanation, confidence_label, risk_indicators, counter_signals.
"""

    @classmethod
    def generate_investigation_reasoning(
        cls,
        case_id: str,
        trigger_type: str,
        trigger_reason: str,
        priority: str,
        evidence_items: List[Dict[str, Any]],
        graph_analysis: Dict[str, Any],
        retrieved_policies: List[Dict[str, Any]],
        missing_evidence: List[str],
        rule_evaluation_results: Dict[str, Any] = None,
        historical_patterns: List[Dict[str, Any]] = None,
        evidence_lifecycle: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Executes LangChain structured reasoning across primary LLM (Gemini)
        with automatic failover strictly to secondary LLM (Mistral).
        Zero mock fallbacks allowed as per system policy.
        """
        primary_provider = LLMProviderFactory.get_provider()
        fallback_provider = LLMProviderFactory.get_fallback_provider()

        prompt = cls._build_investigation_prompt(
            case_id=case_id,
            trigger_type=trigger_type,
            trigger_reason=trigger_reason,
            priority=priority,
            evidence_items=evidence_items,
            graph_analysis=graph_analysis,
            retrieved_policies=retrieved_policies,
            missing_evidence=missing_evidence,
            rule_evaluation_results=rule_evaluation_results or {},
            historical_patterns=historical_patterns or [],
            evidence_lifecycle=evidence_lifecycle,
        )

        dispatch_start = time.time()
        rule_res = rule_evaluation_results or {}
        trig_rules = [r.get("rule_id") for r in rule_res.get("triggered_rules", [])]

        print("\n" + "=" * 80, flush=True)
        print(f"🤖 [LANGCHAIN INVESTIGATION DISPATCH] Case: {case_id}", flush=True)
        print(f"   Primary LLM:   {primary_provider.provider_name.upper()} ({primary_provider.model_name})", flush=True)
        print(f"   Fallback LLM:  {fallback_provider.provider_name.upper()} ({fallback_provider.model_name})", flush=True)
        print(f"   Trigger Type:  {trigger_type} (Priority: {priority})", flush=True)
        print(f"   Trigger Note:  {trigger_reason[:75]}...", flush=True)
        print(f"   Grounding:     Evidence Items: {len(evidence_items)} | Active Policies: {len(retrieved_policies)} | Triggered Rules: {trig_rules or 'None'}", flush=True)
        print("-" * 80, flush=True)

        # ── 1. Attempt Primary LLM (Gemini) ──────────────────────────────────
        primary_error = None
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"▶️  [Attempt {attempt}/{max_attempts}] Querying Primary LLM [{primary_provider.provider_name.upper()}] via LangChain structured output...", flush=True)
                output: LLMInvestigationOutput = primary_provider.generate_structured(
                    prompt=prompt,
                    system_prompt=cls.SYSTEM_PROMPT
                )

                model_tag = f"{primary_provider.provider_name}/{primary_provider.model_name}"
                total_elapsed = round(time.time() - dispatch_start, 2)
                print("-" * 80, flush=True)
                print(f"✅ [LANGCHAIN SYNTHESIS SUCCESS] Completed in {total_elapsed}s by {model_tag}", flush=True)
                print(f"   Assessment:          {output.assessment}", flush=True)
                print(f"   Action Proposal:     {output.recommendation}", flush=True)
                print(f"   Confidence Level:    {output.confidence_label}", flush=True)
                print(f"   Risk Indicators:     {len(output.risk_indicators)} detected", flush=True)
                print(f"   Forensic Summary:    {output.explanation[:120]}...", flush=True)
                print("=" * 80 + "\n", flush=True)

                logger.info(f"LLM reasoning successfully synthesized by {model_tag}: {output.assessment} -> {output.recommendation}")
                return {
                    "assessment": output.assessment,
                    "recommendation": output.recommendation,
                    "explanation": output.explanation,
                    "confidence_label": output.confidence_label,
                    "risk_indicators": [item.model_dump() for item in output.risk_indicators],
                    "counter_signals": [item.model_dump() for item in output.counter_signals],
                    "model_name": model_tag
                }
            except Exception as e:
                primary_error = e
                print(f"⚠️  [Primary Attempt {attempt} Error] {e}", flush=True)
                logger.warning(f"Primary LLM attempt {attempt} failed: {e}")
                if attempt < max_attempts:
                    time.sleep(1.0)

        # ── 2. Failover to Fallback LLM (Mistral) ────────────────────────────
        print("-" * 80, flush=True)
        print(f"🔄 [LLM FAILOVER ACTIVATED] Primary LLM ({primary_provider.provider_name}) unavailable: {primary_error}", flush=True)
        print(f"   Switching to fallback LLM: MISTRAL ({fallback_provider.model_name}) via LangChain...", flush=True)
        print("-" * 80, flush=True)
        logger.warning(f"Primary LLM exhausted. Engaging fallback Mistral LLM: {primary_error}")

        fallback_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"▶️  [Fallback Attempt {attempt}/{max_attempts}] Querying Mistral LLM via LangChain structured output...", flush=True)
                output: LLMInvestigationOutput = fallback_provider.generate_structured(
                    prompt=prompt,
                    system_prompt=cls.SYSTEM_PROMPT
                )

                model_tag = f"mistral/{fallback_provider.model_name} (Fallback)"
                total_elapsed = round(time.time() - dispatch_start, 2)
                print("-" * 80, flush=True)
                print(f"✅ [FALLBACK MISTRAL SYNTHESIS SUCCESS] Completed in {total_elapsed}s by {model_tag}", flush=True)
                print(f"   Assessment:          {output.assessment}", flush=True)
                print(f"   Action Proposal:     {output.recommendation}", flush=True)
                print(f"   Confidence Level:    {output.confidence_label}", flush=True)
                print(f"   Risk Indicators:     {len(output.risk_indicators)} detected", flush=True)
                print(f"   Forensic Summary:    {output.explanation[:120]}...", flush=True)
                print("=" * 80 + "\n", flush=True)

                logger.info(f"Fallback Mistral reasoning successfully synthesized by {model_tag}: {output.assessment} -> {output.recommendation}")
                return {
                    "assessment": output.assessment,
                    "recommendation": output.recommendation,
                    "explanation": output.explanation,
                    "confidence_label": output.confidence_label,
                    "risk_indicators": [item.model_dump() for item in output.risk_indicators],
                    "counter_signals": [item.model_dump() for item in output.counter_signals],
                    "model_name": model_tag
                }
            except Exception as e:
                fallback_error = e
                print(f"⚠️  [Fallback Mistral Attempt {attempt} Error] {e}", flush=True)
                logger.warning(f"Fallback Mistral attempt {attempt} failed: {e}")
                if attempt < max_attempts:
                    time.sleep(1.0)

        # ── 3. Strict Zero-Mock Policy ───────────────────────────────────────
        print("-" * 80, flush=True)
        print(f"❌ [ALL REAL LLMs FAILED] Both Primary ({primary_provider.provider_name}) and Fallback ({fallback_provider.provider_name}) failed.", flush=True)
        print("   Zero mock data permitted under user specification.", flush=True)
        print("=" * 80 + "\n", flush=True)

        raise RuntimeError(
            f"All real LLM providers failed and no mock fallbacks are permitted. "
            f"Primary ({primary_provider.provider_name}) error: {primary_error}. "
            f"Fallback ({fallback_provider.provider_name}) error: {fallback_error}."
        )

    @classmethod
    def _fallback_deterministic_reasoning(
        cls,
        case_id: str,
        trigger_type: str,
        trigger_reason: str,
        priority: str,
        evidence_items: list,
        graph_analysis: dict,
        retrieved_policies: list,
        rule_evaluation_results: dict,
        historical_patterns: list,
        evidence_lifecycle: dict = None,
    ) -> dict:
        """
        Deterministic rule-based synthesizer preserved for offline unit testing.
        """
        rule_results = rule_evaluation_results or {}
        triggered = rule_results.get("triggered_rules", [])
        total_score = rule_results.get("total_risk_score", 0.0)
        highest_severity = rule_results.get("highest_severity", "LOW")

        risk_indicators = []
        for r in triggered:
            risk_indicators.append({
                "statement": f"Triggered fraud rule {r.get('rule_id')}: {r.get('rule_name')} (severity: {r.get('severity')}, observed: {r.get('observed_value')}, threshold: {r.get('threshold_value')})",
                "evidence_references": [e.get("id") for e in evidence_items if e.get("id")]
            })

        signals = (graph_analysis or {}).get("risk_signals", [])
        for s in signals:
            risk_indicators.append({
                "statement": f"Graph Entity Risk: {s.get('signal')} - {s.get('detail')}",
                "evidence_references": []
            })

        is_user_blocked_in_db = False
        target_user_status = None
        for item in (evidence_items or []):
            if item.get("evidence_type") == "USER_PROFILE":
                payload = item.get("normalized_payload") or {}
                target_user_status = payload.get("status")
                if target_user_status in ["BLOCKED", "SUSPENDED", "LOCKED"]:
                    is_user_blocked_in_db = True
                break

        device_ban_evasion = (
            (graph_analysis or {}).get("device_ban_evasion_detected") or
            any(d.get("is_tainted_device") for d in (graph_analysis or {}).get("shared_devices", []))
        )

        if is_user_blocked_in_db or (priority == "CRITICAL" and "CURRENTLY BLOCKED" in trigger_reason):
            assessment = "SUSPICIOUS"
            recommendation = "BLOCK_USER"
            confidence = "HIGH"
        elif device_ban_evasion:
            assessment = "SUSPICIOUS"
            recommendation = "BLOCK_USER"
            confidence = "HIGH"
            tainted_devices = [d for d in (graph_analysis or {}).get("shared_devices", []) if d.get("is_tainted_device")]
            for td in tainted_devices:
                dev_id = td.get("device_id")
                blocked_accs = [f"{b.get('user_id')} ({b.get('name')})" for b in td.get("blocked_accounts", [])]
                risk_indicators.append({
                    "statement": f"🚨 Hardware Ban Evasion Alert: Device '{dev_id}' is physically linked to BLOCKED fraudster account(s): {', '.join(blocked_accs)}.",
                    "evidence_references": []
                })
        elif evidence_lifecycle and (evidence_lifecycle.get("token_status") == "SUBMITTED" or evidence_lifecycle.get("status") == "SUBMITTED"):
            assessment = "NOT_SUBSTANTIATED"
            recommendation = "UNLOCK_USER"
            confidence = "HIGH"
        elif evidence_lifecycle and (evidence_lifecycle.get("token_status") in ["ISSUED", "PENDING", "ACCESSED"]):
            assessment = "INCONCLUSIVE"
            recommendation = "TEMPORARY_RESTRICTION"
            confidence = "MEDIUM"
        elif highest_severity == "CRITICAL" or total_score >= 0.35:
            assessment = "SUSPICIOUS"
            recommendation = "BLOCK_USER" if any(r.get("rule_id") == "FR-001" for r in triggered) else "BLOCK_TRANSACTION"
            confidence = "HIGH"
        elif highest_severity == "HIGH" or total_score >= 0.20:
            assessment = "SUSPICIOUS"
            recommendation = "HOLD_TRANSACTION"
            confidence = "HIGH"
        elif highest_severity == "MEDIUM" or total_score >= 0.10:
            assessment = "INCONCLUSIVE"
            recommendation = "REQUEST_VERIFICATION"
            confidence = "MEDIUM"
        else:
            assessment = "NOT_SUBSTANTIATED"
            recommendation = "MONITOR"
            confidence = "LOW"

        explanation = (
            f"Deterministic Forensic Synthesis: Case evaluated against structured fraud knowledgebase. "
            f"Rule Engine identified {len(triggered)} triggered rule(s) with total risk score of {total_score:.2f} "
            f"and highest severity '{highest_severity}'. Trigger reason: '{trigger_reason}'. "
            f"Grounding evidence references: {len(evidence_items)} item(s) collected."
        )

        return {
            "assessment": assessment,
            "recommendation": recommendation,
            "explanation": explanation,
            "confidence_label": confidence,
            "risk_indicators": risk_indicators,
            "counter_signals": [],
            "model_name": "Deterministic-RuleEngine"
        }

    @classmethod
    def _build_investigation_prompt(
        cls,
        case_id: str,
        trigger_type: str,
        trigger_reason: str,
        priority: str,
        evidence_items: List[Dict[str, Any]],
        graph_analysis: Dict[str, Any],
        retrieved_policies: List[Dict[str, Any]],
        missing_evidence: List[str],
        rule_evaluation_results: Dict[str, Any] = None,
        historical_patterns: List[Dict[str, Any]] = None,
        evidence_lifecycle: Dict[str, Any] = None,
    ) -> str:
        prompt_sections = [
            f"CASE METADATA:",
            f"- Case ID: {case_id}",
            f"- Trigger Type: {trigger_type}",
            f"- Trigger Reason: {trigger_reason}",
            f"- Priority: {priority}",
            "",
            "COLLECTED FORENSIC EVIDENCE:"
        ]

        if not evidence_items:
            prompt_sections.append("- (No evidence items retrieved from upstream domain tables)")
        else:
            for item in evidence_items:
                ev_id = item.get("id", "UNKNOWN")
                ev_type = item.get("evidence_type", "UNKNOWN")
                status = item.get("retrieval_status", "UNKNOWN")
                payload = item.get("normalized_payload") or {}
                prompt_sections.append(f"- Evidence ID [{ev_id}] Type: {ev_type} (Status: {status}): {json.dumps(payload)}")

        if missing_evidence:
            prompt_sections.append("")
            prompt_sections.append(f"MISSING EVIDENCE: {', '.join(missing_evidence)}")

        prompt_sections.append("")
        prompt_sections.append("GRAPH ENTITY CORRELATION:")
        prompt_sections.append(json.dumps(graph_analysis, indent=2))

        prompt_sections.append("")
        prompt_sections.append("RETRIEVED POLICY GUIDELINES:")
        if not retrieved_policies:
            prompt_sections.append("- No specific policy guidelines retrieved for this case.")
        else:
            for p in retrieved_policies:
                prompt_sections.append(f"- Policy: {p.get('document_key', 'POLICY')}: {p.get('text', '')}")

        is_user_unregistered = any(
            item.get("evidence_type") == "USER_PROFILE" and item.get("retrieval_status") == "MISSING"
            for item in evidence_items
        ) or any("USER_PROFILE" in str(m) for m in missing_evidence)

        if is_user_unregistered:
            prompt_sections.append("")
            prompt_sections.append("CRITICAL INSTRUCTION - UNREGISTERED ENTITY / MISSING USER RECORD:")
            prompt_sections.append("- The target entity does NOT exist in the core m_users directory (no account, no orders, no transaction history).")
            prompt_sections.append("- Your explanation must directly and clearly state that this user's details do not exist in the master database (m_users).")
            prompt_sections.append("- Do NOT describe network risk as 'normal' (there is no network/device footprint) and do NOT recommend customer 'step-up authentication' (since there is no existing account to authenticate).")
            prompt_sections.append("- Output assessment as 'SUSPICIOUS' and recommendation as 'BLOCK_USER' or 'ESCALATE' to prevent unauthorized processing for non-existent users.")

        prompt_sections.append("")
        if rule_evaluation_results:
            triggered = rule_evaluation_results.get("triggered_rules", [])
            score = rule_evaluation_results.get("total_risk_score", 0.0)
            severity = rule_evaluation_results.get("highest_severity", "NONE")
            prompt_sections.append("DETERMINISTIC RULE ENGINE RESULTS (pre-computed, authoritative):")
            prompt_sections.append(f"- Composite Risk Score: {score:.2f} / 1.00")
            prompt_sections.append(f"- Highest Triggered Severity: {severity}")
            if triggered:
                prompt_sections.append("- TRIGGERED RULES (violations that MUST be cited in your explanation):")
                for r in triggered:
                    prompt_sections.append(
                        f"  * [{r['rule_id']}] {r['rule_name']} | Severity: {r['severity']} | "
                        f"Observed: {r['observed_value']} | Threshold: {r['threshold_value']} {r.get('threshold_unit','')} | Note: {r['note']}"
                    )
            else:
                prompt_sections.append("- No fraud rules triggered (all rules passed).")
            prompt_sections.append("IMPORTANT: You MUST NOT perform any arithmetic. Accept these rule results as ground truth.")

        if historical_patterns:
            prompt_sections.append("")
            prompt_sections.append("HISTORICAL CASE PRECEDENTS (confirmed past outcomes):")
            for hp in historical_patterns[:3]:
                prompt_sections.append(
                    f"- Case {hp.get('case_id','?')} | Disposition: {hp.get('final_disposition')} "
                    f"| Rules: {hp.get('triggered_rule_ids')} | Notes: {hp.get('analyst_notes','')[:120]}"
                )

        # Check if user profile is already BLOCKED or SUSPENDED
        is_user_blocked_in_db = False
        target_user_status = None
        for item in (evidence_items or []):
            if item.get("evidence_type") == "USER_PROFILE":
                payload = item.get("normalized_payload") or {}
                target_user_status = payload.get("status")
                if target_user_status in ["BLOCKED", "SUSPENDED", "LOCKED"]:
                    is_user_blocked_in_db = True
                break

        if is_user_blocked_in_db or (priority == "CRITICAL" and "CURRENTLY BLOCKED" in trigger_reason):
            prompt_sections.append("")
            prompt_sections.append("CRITICAL INSTRUCTION - TARGET ENTITY IN BLOCKED / ENFORCED STATUS:")
            prompt_sections.append(f"- The target user is CURRENTLY recorded with status '{target_user_status or 'BLOCKED'}' in master table m_users.")
            prompt_sections.append("- This entity was previously investigated and placed under enforcement. Any subsequent activity represents repeated or unauthorized access attempts.")
            prompt_sections.append("- Your assessment MUST be 'SUSPICIOUS' and recommendation MUST be 'BLOCK_USER' (Maintain Hard Block) or 'ESCALATE'.")
            prompt_sections.append("- You MUST explicitly cite in your explanation that the user is currently locked/blocked in the master database.")

        device_ban_evasion = (
            (graph_analysis or {}).get("device_ban_evasion_detected") or
            any(d.get("is_tainted_device") for d in (graph_analysis or {}).get("shared_devices", []))
        )
        if device_ban_evasion:
            tainted_devices = [d for d in (graph_analysis or {}).get("shared_devices", []) if d.get("is_tainted_device")]
            prompt_sections.append("")
            prompt_sections.append("CRITICAL INSTRUCTION - HARDWARE BAN EVASION (DEVICE-LEVEL FRAUD TAINT):")
            for td in tainted_devices:
                dev_id = td.get("device_id")
                blocked_accs = [f"{b.get('user_id')} ({b.get('name')})" for b in td.get("blocked_accounts", [])]
                prompt_sections.append(
                    f"- The hardware device '{dev_id}' used in this transaction was previously used by confirmed BLOCKED fraudster(s): {', '.join(blocked_accs)}."
                )
            prompt_sections.append("- This indicates an active BAN EVASION attempt (a blocked fraudster creating or operating an alternate account from the same physical hardware).")
            prompt_sections.append("- Your assessment MUST be 'SUSPICIOUS' and recommendation MUST be 'BLOCK_USER'.")
            prompt_sections.append("- You MUST explicitly cite the tainted device ID and the name/ID of the linked blocked fraudster in your explanation.")

        if evidence_lifecycle:
            tok_status = evidence_lifecycle.get("token_status") or evidence_lifecycle.get("status")
            req_docs = evidence_lifecycle.get("requested_documents", [])
            submitted_at = evidence_lifecycle.get("submitted_at")
            sub_payload = evidence_lifecycle.get("submission_payload") or {}
            user_exp = sub_payload.get("user_explanation", "")

            prompt_sections.append("")
            prompt_sections.append("CUSTOMER VERIFICATION / EVIDENCE LIFECYCLE:")
            if tok_status == "SUBMITTED":
                prompt_sections.append(f"- Verification Documents: SUBMITTED via Customer Evidence Portal on {submitted_at or 'recently'}.")
                prompt_sections.append(f"- Requested Types: {', '.join(req_docs) if req_docs else 'Identity verification'}")
                if user_exp:
                    prompt_sections.append("- Customer Explanation: " + repr(user_exp))
                prompt_sections.append("- INSTRUCTION: The customer has provided the requested evidence documents. Evaluate whether this counter-evidence resolves the initial suspicion. If satisfactory and valid, recommend 'UNLOCK_USER' or 'NO_ACTION'. If suspicious or counterfeit, recommend 'BLOCK_USER' or 'ESCALATE'.")
            elif tok_status in ["ISSUED", "ACCESSED", "VERIFIED", "PENDING"]:
                prompt_sections.append(f"- Verification Documents: PENDING (Customer has NOT yet uploaded required verification documents).")
                prompt_sections.append(f"- Requested Types: {', '.join(req_docs) if req_docs else 'Govt ID / Proof of Address'}")
                prompt_sections.append("- INSTRUCTION: Because mandatory evidence is still pending, you MUST recommend 'TEMPORARY_RESTRICTION' or 'HOLD_TRANSACTION'. Do NOT recommend account unlock or transaction clearance until evidence is uploaded.")

        prompt_sections.append("Synthesize the case and output your structured decision now:")
        return "\n".join(prompt_sections)
