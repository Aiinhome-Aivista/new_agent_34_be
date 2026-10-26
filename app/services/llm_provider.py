import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import httpx

from app.config import Config
from app.schemas.recommendation import StructuredRecommendation, IndicatorItem

logger = logging.getLogger("fraud_agent.llm_provider")


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


class BaseLLMProvider(ABC):
    """Abstract interface for LLM reasoning providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None, json_mode: bool = True) -> str:
        """Generates text completion from the LLM."""
        pass

    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        """Returns readiness / operational status of the provider."""
        pass


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider via Generative Language REST API."""

    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self.model = Config.GEMINI_MODEL or "gemini-1.5-flash"
        self.timeout = float(Config.LLM_TIMEOUT or 60)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self.model

    def generate(self, prompt: str, system_prompt: Optional[str] = None, json_mode: bool = True) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured in environment.")

        # Google Gemini API endpoint
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"SYSTEM INSTRUCTIONS:\n{system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will strictly follow all system instructions and output format requirements."}]})

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        generation_config = {
            "temperature": 0.2,
        }
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload = {
            "contents": contents,
            "generationConfig": generation_config
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned empty candidate list.")

            first_candidate = candidates[0]
            parts = first_candidate.get("content", {}).get("parts", [])
            if not parts:
                raise ValueError("Gemini candidate contains no content parts.")

            return parts[0].get("text", "")

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "message": "GEMINI_API_KEY is missing"}
        return {"status": "CONFIGURED", "model": self.model}


class OpenAIProvider(BaseLLMProvider):
    """OpenAI ChatGPT / GPT-4o provider."""

    def __init__(self):
        self.api_key = Config.OPENAI_API_KEY
        self.model = Config.OPENAI_MODEL or "gpt-4o-mini"
        base_url = Config.OPENAI_BASE_URL.strip() if Config.OPENAI_BASE_URL else "https://api.openai.com/v1"
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.timeout = float(Config.LLM_TIMEOUT or 60)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self.model

    def generate(self, prompt: str, system_prompt: Optional[str] = None, json_mode: bool = True) -> str:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not configured in environment.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "message": "OPENAI_API_KEY is missing"}
        return {"status": "CONFIGURED", "model": self.model}


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude LLM provider."""

    def __init__(self):
        self.api_key = Config.ANTHROPIC_API_KEY
        self.model = Config.ANTHROPIC_MODEL or "claude-3-5-sonnet-20241022"
        self.url = "https://api.anthropic.com/v1/messages"
        self.timeout = float(Config.LLM_TIMEOUT or 60)

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def model_name(self) -> str:
        return self.model

    def generate(self, prompt: str, system_prompt: Optional[str] = None, json_mode: bool = True) -> str:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured in environment.")

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        user_content = prompt
        if json_mode:
            user_content = f"{prompt}\n\nIMPORTANT: Respond ONLY with valid JSON. Do not include markdown code block formatting or explanations outside JSON."

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": user_content}],
            "max_tokens": 4096,
            "temperature": 0.2
        }
        if system_prompt:
            payload["system"] = system_prompt

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "NOT_CONFIGURED", "message": "ANTHROPIC_API_KEY is missing"}
        return {"status": "CONFIGURED", "model": self.model}


class AzureOpenAIProvider(BaseLLMProvider):
    """Azure OpenAI / Copilot provider."""

    def __init__(self):
        self.api_key = Config.AZURE_OPENAI_API_KEY
        endpoint = Config.AZURE_OPENAI_ENDPOINT.rstrip('/') if Config.AZURE_OPENAI_ENDPOINT else ""
        deployment = Config.AZURE_OPENAI_DEPLOYMENT or "gpt-4o"
        api_version = Config.AZURE_OPENAI_API_VERSION or "2024-02-01"
        self.model = deployment
        self.url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        self.timeout = float(Config.LLM_TIMEOUT or 60)

    @property
    def provider_name(self) -> str:
        return "azure_openai"

    @property
    def model_name(self) -> str:
        return self.model

    def generate(self, prompt: str, system_prompt: Optional[str] = None, json_mode: bool = True) -> str:
        if not self.api_key or not Config.AZURE_OPENAI_ENDPOINT:
            raise ValueError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be configured.")

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "temperature": 0.2
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def check_health(self) -> Dict[str, Any]:
        if not self.api_key or not Config.AZURE_OPENAI_ENDPOINT:
            return {"status": "NOT_CONFIGURED", "message": "Azure OpenAI credentials missing"}
        return {"status": "CONFIGURED", "model": self.model}


class CustomLocalLLMProvider(BaseLLMProvider):
    """
    Local / Custom LLM Provider supporting:
    - Ollama /generate endpoint (e.g. http://122.163.121.176:3041/api/generate)
    - Ollama /chat endpoint
    - vLLM / LocalAI / OpenAI-compatible local servers
    """

    def __init__(self):
        self.api_url = Config.LLM_API_URL or "http://122.163.121.176:3041/api/generate"
        self.model = Config.LLM_MODEL or "mistral-small:24b"
        self.timeout = float(Config.LLM_TIMEOUT or 300)

    @property
    def provider_name(self) -> str:
        return "custom"

    @property
    def model_name(self) -> str:
        return self.model

    def generate(self, prompt: str, system_prompt: Optional[str] = None, json_mode: bool = True) -> str:
        if not self.api_url:
            raise ValueError("LLM_API_URL is not configured.")

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"System Instruction:\n{system_prompt}\n\nTask:\n{prompt}"

        # Detect endpoint format
        is_ollama_generate = self.api_url.rstrip("/").endswith("/api/generate")
        is_ollama_chat = self.api_url.rstrip("/").endswith("/api/chat")

        with httpx.Client(timeout=self.timeout) as client:
            if is_ollama_generate:
                payload: Dict[str, Any] = {
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": 0.2}
                }
                if json_mode:
                    payload["format"] = "json"

                resp = client.post(self.api_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")

            elif is_ollama_chat:
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.2}
                }
                if json_mode:
                    payload["format"] = "json"

                resp = client.post(self.api_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", "")

            else:
                # Default to OpenAI-compatible chat completion payload
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                payload = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2
                }
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}

                resp = client.post(self.api_url, json=payload)
                resp.raise_for_status()
                data = resp.json()

                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
                elif "response" in data:
                    return data["response"]
                else:
                    return str(data)

    def check_health(self) -> Dict[str, Any]:
        if not self.api_url:
            return {"status": "NOT_CONFIGURED", "message": "LLM_API_URL missing"}
        return {"status": "CONFIGURED", "model": self.model, "endpoint": self.api_url}


class LLMProviderFactory:
    """Factory to instantiate and manage LLM reasoning providers."""

    @staticmethod
    def get_provider(provider_type: Optional[str] = None) -> BaseLLMProvider:
        active = (provider_type or Config.LLM_PROVIDER or "custom").lower().strip()

        if active == "gemini":
            return GeminiProvider()
        elif active == "openai":
            return OpenAIProvider()
        elif active == "claude":
            return ClaudeProvider()
        elif active == "azure_openai":
            return AzureOpenAIProvider()
        elif active in ["custom", "mistral", "ollama", "local"]:
            return CustomLocalLLMProvider()
        else:
            logger.warning(f"Unknown LLM provider '{active}', falling back to Custom/Local provider.")
            return CustomLocalLLMProvider()


class LLMReasoningService:
    """High-level service orchestrating structured investigation reasoning."""

    SYSTEM_PROMPT = """You are Agent 34, an autonomous forensic fraud investigator for e-commerce, banking, and payment operations.
Your job is to analyze forensic evidence (user profile, transaction details, payments, dispute/chargeback history, and multi-hop graph networks) alongside relevant company policies.

CRITICAL REQUIREMENTS:
1. Ground every risk indicator and counter signal strictly in the provided evidence. Cite valid evidence IDs.
2. Never hallucinate facts or missing data.
3. You must output ONLY a valid JSON object matching the exact specification below. Do not wrap in markdown or add conversational preamble.

Required JSON Structure:
{
  "assessment": "SUSPICIOUS" | "NOT_SUBSTANTIATED" | "INCONCLUSIVE",
  "recommendation": "NO_ACTION" | "MONITOR" | "REQUEST_VERIFICATION" | "SEND_NOTIFICATION" | "TEMPORARY_RESTRICTION" | "HOLD_TRANSACTION" | "BLOCK_TRANSACTION" | "BLOCK_USER" | "BLOCK_MERCHANT" | "ESCALATE",
  "explanation": "Detailed professional reasoning explaining findings, citing evidence and risk levels (minimum 25 words).",
  "confidence_label": "HIGH" | "MEDIUM" | "LOW",
  "risk_indicators": [
    {
      "statement": "Clear factual risk statement",
      "evidence_references": ["evidence_id_1"]
    }
  ],
  "counter_signals": [
    {
      "statement": "Factual mitigating statement e.g. KYC verified, longstanding account",
      "evidence_references": ["evidence_id_2"]
    }
  ]
}"""

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
        missing_evidence: List[str]
    ) -> Dict[str, Any]:
        """
        Executes LLM reasoning across configured provider with guaranteed fallback.
        """
        provider = LLMProviderFactory.get_provider()
        model_tag = f"{provider.provider_name}/{provider.model_name}"

        prompt = cls._build_investigation_prompt(
            case_id=case_id,
            trigger_type=trigger_type,
            trigger_reason=trigger_reason,
            priority=priority,
            evidence_items=evidence_items,
            graph_analysis=graph_analysis,
            retrieved_policies=retrieved_policies,
            missing_evidence=missing_evidence
        )

        try:
            logger.info(f"Dispatching investigation reasoning to LLM Provider: {provider.provider_name} ({provider.model_name})")
            raw_response = provider.generate(prompt=prompt, system_prompt=cls.SYSTEM_PROMPT, json_mode=True)
            parsed_json = extract_json_from_response(raw_response)

            if parsed_json and "assessment" in parsed_json and "recommendation" in parsed_json:
                # Validate recommendation type is acceptable
                rec = parsed_json.get("recommendation", "MONITOR")
                valid_recs = {
                    "NO_ACTION", "MONITOR", "REQUEST_VERIFICATION", "SEND_NOTIFICATION",
                    "TEMPORARY_RESTRICTION", "HOLD_TRANSACTION", "BLOCK_TRANSACTION",
                    "BLOCK_USER", "BLOCK_MERCHANT", "ESCALATE"
                }
                if rec not in valid_recs:
                    rec = "REQUEST_VERIFICATION" if parsed_json.get("assessment") == "INCONCLUSIVE" else "MONITOR"

                # Validate assessment
                assessment = parsed_json.get("assessment", "INCONCLUSIVE")
                if assessment not in {"SUSPICIOUS", "NOT_SUBSTANTIATED", "INCONCLUSIVE"}:
                    assessment = "INCONCLUSIVE"

                confidence = parsed_json.get("confidence_label", "MEDIUM")
                if confidence not in {"HIGH", "MEDIUM", "LOW"}:
                    confidence = "MEDIUM"

                explanation = parsed_json.get("explanation", "").strip()
                if len(explanation) < 20:
                    explanation = f"Automated analysis completed by {model_tag}: Evidence synthesized for {trigger_type} with confidence {confidence}."

                risk_indicators = parsed_json.get("risk_indicators", [])
                counter_signals = parsed_json.get("counter_signals", [])

                logger.info(f"LLM reasoning successfully synthesized by {model_tag} with assessment: {assessment}, recommendation: {rec}")
                return {
                    "assessment": assessment,
                    "recommendation": rec,
                    "explanation": explanation,
                    "confidence_label": confidence,
                    "risk_indicators": risk_indicators,
                    "counter_signals": counter_signals,
                    "model_name": model_tag
                }
            else:
                logger.warning(f"LLM response did not contain expected schema fields. Raw response: {raw_response[:200]}")
        except Exception as e:
            logger.warning(f"LLM Provider invocation failed or timed out ({provider.provider_name}): {e}. Applying evidence-grounded deterministic fallback.")

        # Deterministic Grounded Fallback
        return cls._deterministic_grounded_fallback(
            evidence_items=evidence_items,
            graph_analysis=graph_analysis,
            missing_evidence=missing_evidence,
            model_tag=f"{model_tag} (Fallback Engine)"
        )

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
        missing_evidence: List[str]
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
            prompt_sections.append("- Default Fraud Investigation SOP: Any dispute rate > 1% or multi-account device rings warrant temporary protective restriction.")
        else:
            for p in retrieved_policies:
                prompt_sections.append(f"- Policy: {p.get('document_key', 'POLICY')}: {p.get('text', '')}")

        prompt_sections.append("")
        prompt_sections.append("Synthesize the case and output your structured decision JSON now:")
        return "\n".join(prompt_sections)

    @classmethod
    def _deterministic_grounded_fallback(
        cls,
        evidence_items: List[Dict[str, Any]],
        graph_analysis: Dict[str, Any],
        missing_evidence: List[str],
        model_tag: str
    ) -> Dict[str, Any]:
        """Provides guaranteed rule-based evidence synthesis if LLM provider is offline."""
        risk_indicators = []
        counter_signals = []
        has_chargebacks = False
        has_high_network_risk = graph_analysis.get("network_risk_indicator") == "HIGH"

        for ev in evidence_items:
            ev_id = ev.get("id")
            ev_type = ev.get("evidence_type")
            payload = ev.get("normalized_payload") or {}

            if ev_type == "CHARGEBACK_HISTORY":
                dispute_count = payload.get("count", 0)
                if dispute_count > 0:
                    has_chargebacks = True
                    risk_indicators.append({
                        "statement": f"Dispute history identified: {dispute_count} recorded chargeback dispute(s).",
                        "evidence_references": [ev_id]
                    })

            if ev_type == "USER_PROFILE":
                kyc = payload.get("kyc_status")
                risk_level = payload.get("risk_level")
                if kyc == "VERIFIED":
                    counter_signals.append({
                        "statement": "Customer identity is fully verified with VERIFIED KYC status.",
                        "evidence_references": [ev_id]
                    })
                if risk_level == "HIGH":
                    risk_indicators.append({
                        "statement": "Upstream source system flagged customer profile risk level as HIGH.",
                        "evidence_references": [ev_id]
                    })

        if has_high_network_risk:
            shared_dev = graph_analysis.get("shared_devices_count", 0)
            risk_indicators.append({
                "statement": f"Entity graph traversal detected multiple users sharing {shared_dev} common hardware device(s).",
                "evidence_references": []
            })

        if has_chargebacks or has_high_network_risk:
            assessment = "SUSPICIOUS"
            recommendation = "HOLD_TRANSACTION"
            confidence = "HIGH"
            explanation = (
                f"Substantiated risk indicators detected across {len(risk_indicators)} material evidence sources. "
                f"Evidence indicates dispute anomalies or shared device clusters. Advising protective hold pending analyst review."
            )
        elif len(missing_evidence) > 0 and len(evidence_items) <= len(missing_evidence):
            assessment = "INCONCLUSIVE"
            recommendation = "REQUEST_VERIFICATION"
            confidence = "LOW"
            explanation = f"Insufficient source evidence retrieved. Critical records are missing: {', '.join(missing_evidence)}."
        else:
            assessment = "NOT_SUBSTANTIATED"
            recommendation = "MONITOR"
            confidence = "MEDIUM"
            explanation = "Retrieved evidence does not substantiate anomalous merchant or user fraud. Continued monitoring advised."

        return {
            "assessment": assessment,
            "recommendation": recommendation,
            "explanation": explanation,
            "confidence_label": confidence,
            "risk_indicators": risk_indicators,
            "counter_signals": counter_signals,
            "model_name": model_tag
        }
