import json
import time
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

        t0 = time.time()
        print(f"   🌐 [LLM-HTTP] >>> POST {url.split('?')[0]} (Model: {self.model})", flush=True)
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            elapsed = round(time.time() - t0, 2)
            print(f"   🌐 [LLM-HTTP] <<< HTTP {resp.status_code} received in {elapsed}s", flush=True)
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
            raise ValueError(f"Unknown or unsupported LLM provider '{active}'. Please configure a valid provider in .env.")


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
        missing_evidence: List[str],
        # Phase 3: Knowledgebase intelligence grounding inputs
        rule_evaluation_results: Dict[str, Any] = None,
        historical_patterns: List[Dict[str, Any]] = None,
        evidence_lifecycle: Dict[str, Any] = None,
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
            missing_evidence=missing_evidence,
            rule_evaluation_results=rule_evaluation_results or {},
            historical_patterns=historical_patterns or [],
            evidence_lifecycle=evidence_lifecycle,
        )

        # Prominent Terminal Logging for Investigation Reasoning
        dispatch_start = time.time()
        rule_res = rule_evaluation_results or {}
        trig_rules = [r.get("rule_id") for r in rule_res.get("triggered_rules", [])]

        print("\n" + "=" * 80, flush=True)
        print(f"🤖 [LLM INVESTIGATION DISPATCH] Case: {case_id}", flush=True)
        print(f"   Provider:      {provider.provider_name.upper()} | Model: {provider.model_name}", flush=True)
        print(f"   Trigger Type:  {trigger_type} (Priority: {priority})", flush=True)
        print(f"   Trigger Note:  {trigger_reason[:75]}...", flush=True)
        print(f"   Grounding:     Evidence Items: {len(evidence_items)} | Active Policies: {len(retrieved_policies)} | Triggered Rules: {trig_rules or 'None'}", flush=True)
        print("-" * 80, flush=True)

        max_attempts = 3
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"▶️  [Attempt {attempt}/{max_attempts}] Querying LLM Engine...", flush=True)
                raw_response = provider.generate(prompt=prompt, system_prompt=cls.SYSTEM_PROMPT, json_mode=True)
                parsed_json = extract_json_from_response(raw_response)

                if parsed_json and "assessment" in parsed_json and "recommendation" in parsed_json:
                    rec = parsed_json.get("recommendation", "MONITOR")
                    valid_recs = {
                        "NO_ACTION", "MONITOR", "REQUEST_VERIFICATION", "SEND_NOTIFICATION",
                        "TEMPORARY_RESTRICTION", "HOLD_TRANSACTION", "BLOCK_TRANSACTION",
                        "BLOCK_USER", "BLOCK_MERCHANT", "ESCALATE"
                    }
                    if rec not in valid_recs:
                        rec = "REQUEST_VERIFICATION" if parsed_json.get("assessment") == "INCONCLUSIVE" else "MONITOR"

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

                    total_elapsed = round(time.time() - dispatch_start, 2)
                    print("-" * 80, flush=True)
                    print(f"✅ [LLM SYNTHESIS SUCCESS] Completed in {total_elapsed}s by {model_tag}", flush=True)
                    print(f"   Assessment:          {assessment}", flush=True)
                    print(f"   Action Proposal:     {rec}", flush=True)
                    print(f"   Confidence Level:    {confidence}", flush=True)
                    print(f"   Risk Indicators:     {len(risk_indicators)} detected", flush=True)
                    print(f"   Forensic Summary:    {explanation[:120]}...", flush=True)
                    print("=" * 80 + "\n", flush=True)

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
                    print(f"⚠️  [Attempt {attempt}] Response missing required schema fields. Retrying...", flush=True)
                    logger.warning(f"LLM response attempt {attempt} missing schema fields. Retrying...")
                    last_error = ValueError("Missing schema fields in response")
            except Exception as e:
                last_error = e
                print(f"⚠️  [Attempt {attempt} Error] {e}", flush=True)
                logger.warning(f"LLM attempt {attempt} failed ({provider.provider_name}): {e}")
                if attempt < max_attempts:
                    retry_wait = round(1.5 * attempt, 1)
                    print(f"⏳ Waiting {retry_wait}s before retry...", flush=True)
                    time.sleep(retry_wait)

        # Fallback to grounded deterministic rule engine reasoning if external LLM is offline/exhausted
        print("-" * 80, flush=True)
        print(f"🛡️  [LLM FALLBACK ENGAGED] External LLM exhausted ({last_error})", flush=True)
        print("   Activating Deterministic Fraud Rule Engine & Entity Graph Synthesis...", flush=True)
        print("=" * 80 + "\n", flush=True)
        logger.warning(f"LLM exhausted all {max_attempts} attempts ({last_error}). Falling back to deterministic rule engine reasoning.")
        return cls._fallback_deterministic_reasoning(
            case_id=case_id,
            trigger_type=trigger_type,
            trigger_reason=trigger_reason,
            priority=priority,
            evidence_items=evidence_items,
            graph_analysis=graph_analysis,
            retrieved_policies=retrieved_policies,
            rule_evaluation_results=rule_evaluation_results,
            historical_patterns=historical_patterns,
            evidence_lifecycle=evidence_lifecycle,
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
        Grounded deterministic fallback synthesis when external LLM provider is unavailable (503 / timeout).
        Uses RuleEngine triggered rules, severity, and evidence directly to ensure zero pipeline stall.
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
            f"Deterministic Forensic Synthesis (LLM Fallback): Case evaluated against structured fraud knowledgebase. "
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
            "model_name": "Deterministic-RuleEngine-Fallback"
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
        # Phase 3 grounding inputs
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
        # --- Phase 3: Deterministic Rule Engine Results ---
        if rule_evaluation_results:
            triggered = rule_evaluation_results.get("triggered_rules", [])
            passed = rule_evaluation_results.get("passed_rules", [])
            score = rule_evaluation_results.get("total_risk_score", 0.0)
            severity = rule_evaluation_results.get("highest_severity", "NONE")
            prompt_sections.append("")
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
        # --- Phase 3: Historical Intelligence ---
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

        # Check for Device-Level Ban Evasion (Hardware Taint from Graph Analysis)
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
            prompt_sections.append("- Your assessment MUST be 'CONFIRMED_FRAUD' or 'SUSPICIOUS' and recommendation MUST be 'BLOCK_USER'.")
            prompt_sections.append("- You MUST explicitly cite the tainted device ID and the name/ID of the linked blocked fraudster in your explanation.")

        # Check evidence & verification lifecycle
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

        is_user_unregistered = any(
            item.get("evidence_type") == "USER_PROFILE" and item.get("retrieval_status") == "MISSING"
            for item in evidence_items
        ) or any("USER_PROFILE" in str(m) for m in missing_evidence)

        if is_user_unregistered:
            return {
                "assessment": "SUSPICIOUS",
                "recommendation": "BLOCK_USER",
                "explanation": "Target user details do not exist in the m_users core database. Unregistered identity with no verified customer profile or account history.",
                "confidence_label": "HIGH",
                "risk_indicators": [{
                    "statement": "Customer identity record was not located in master m_users database.",
                    "evidence_references": [ev.get("id") for ev in evidence_items if ev.get("evidence_type") == "USER_PROFILE"]
                }],
                "counter_signals": [],
                "model_name": model_tag
            }

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
