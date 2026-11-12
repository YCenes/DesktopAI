use crate::text::{ActionClassification, Intent, TextError};
use serde::{Deserialize, Serialize};

fn money(s: &str) -> bool {
    let parts: Vec<_> = s.split('.').collect();
    parts.len() <= 2
        && !parts[0].is_empty()
        && parts[0].len() <= 3
        && parts[0].bytes().all(|c| c.is_ascii_digit())
        && (parts.len() == 1
            || (!parts[1].is_empty()
                && parts[1].len() <= 9
                && parts[1].bytes().all(|c| c.is_ascii_digit())))
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Model {
    pub model_id: String,
    pub input_usd_per_million: String,
    pub output_usd_per_million: String,
    pub price_version: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Usage {
    pub month: String,
    pub monthly_usd: String,
    pub per_task_usd: String,
    pub recorded_usd: String,
    pub reserved_usd: String,
    pub remaining_usd: String,
    pub last_estimate_usd: Option<String>,
    pub last_actual_usd: Option<String>,
    pub last_input_tokens: Option<u64>,
    pub last_output_tokens: Option<u64>,
    pub requests: u64,
    pub blocked: bool,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CloudState {
    pub provider: String,
    pub credential_ready: bool,
    pub enabled: bool,
    pub available: bool,
    pub reason: Option<String>,
    pub model_id: String,
    pub models: Vec<Model>,
    pub usage: Usage,
    pub simulated: bool,
}

impl CloudState {
    pub fn validate(self) -> Result<Self, TextError> {
        let u = &self.usage;
        if !matches!(self.provider.as_str(), "vercel" | "fake")
            || self.simulated != (self.provider == "fake")
            || self.model_id.len() > 96
            || self.models.len() > 4
            || self
                .reason
                .as_ref()
                .is_some_and(|s| s.chars().count() > 512)
            || [
                &u.monthly_usd,
                &u.per_task_usd,
                &u.recorded_usd,
                &u.reserved_usd,
                &u.remaining_usd,
            ]
            .iter()
            .any(|s| !money(s))
            || [&u.last_estimate_usd, &u.last_actual_usd]
                .iter()
                .any(|s| s.as_ref().is_some_and(|s| !money(s)))
            || u.month.len() != 7
            || self.models.iter().any(|m| {
                m.model_id.len() > 96
                    || m.price_version.len() > 64
                    || !money(&m.input_usd_per_million)
                    || !money(&m.output_usd_per_million)
            })
            || (self.available
                && (!self.enabled || !self.credential_ready || self.reason.is_some()))
        {
            return Err(TextError::contract());
        }
        Ok(self)
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CloudConfig {
    pub enabled: bool,
    pub model_id: String,
    pub monthly_usd: String,
    pub per_task_usd: String,
}
impl CloudConfig {
    pub fn validate(&self) -> Result<(), TextError> {
        if self.model_id.len() > 96 || !money(&self.monthly_usd) || !money(&self.per_task_usd) {
            return Err(TextError::contract());
        }
        Ok(())
    }
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChatStatus {
    Running,
    Succeeded,
    Failed,
    Cancelled,
}
#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChatSource {
    Local,
    Offline,
    Cloud,
    Fake,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChatReply {
    pub request_id: String,
    pub status: ChatStatus,
    pub source: ChatSource,
    pub reply: String,
    pub intent: Intent,
    pub action: Option<ActionClassification>,
    pub external_calls: u8,
    pub error_code: Option<String>,
    pub estimated_usd: Option<String>,
    pub actual_usd: Option<String>,
    pub usage_known: bool,
}
impl ChatReply {
    pub fn validate(self, id: &str) -> Result<Self, TextError> {
        if self.request_id != id
            || self.reply.is_empty()
            || self.reply.chars().count() > 4096
            || self.external_calls != u8::from(self.source == ChatSource::Cloud)
            || (self.intent == Intent::ActionRequest) != self.action.is_some()
            || (matches!(
                self.source,
                ChatSource::Cloud | ChatSource::Fake | ChatSource::Offline
            ) && self.intent != Intent::GeneralChat)
            || self.action.as_ref().is_some_and(|a| {
                a.executable || a.target.chars().count() > 1024 || a.target.is_empty()
            })
            || [&self.estimated_usd, &self.actual_usd]
                .iter()
                .any(|s| s.as_ref().is_some_and(|s| !money(s)))
            || self.error_code.as_ref().is_some_and(|s| s.len() > 64)
        {
            return Err(TextError::contract());
        }
        Ok(self)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Cleared {
    pub cleared: bool,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cloud_never_carries_action_or_secret() {
        let value = serde_json::json!({"request_id":"id","status":"succeeded","source":"cloud","reply":"Türkçe yanıt.","intent":"general_chat","action":null,"external_calls":1,"error_code":null,"estimated_usd":"0.001","actual_usd":"0.0001","usage_known":true});
        assert!(serde_json::from_value::<ChatReply>(value.clone())
            .unwrap()
            .validate("id")
            .is_ok());
        let mut bad = value.clone();
        bad["api_key"] = "secret".into();
        assert!(serde_json::from_value::<ChatReply>(bad).is_err());
        let mut bad = value;
        bad["action"] = serde_json::json!({"operation":"open_application","target":"notepad","executable":false});
        assert!(serde_json::from_value::<ChatReply>(bad)
            .unwrap()
            .validate("id")
            .is_err());
    }
    #[test]
    fn money_rejects_nan_negative_and_exponents() {
        for s in ["NaN", "-1", "1e3", "0.0000000001", "", "1."] {
            assert!(!money(s));
        }
        assert!(money("5.000000000"));
    }
}
