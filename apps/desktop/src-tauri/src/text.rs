use serde::{Deserialize, Serialize};

pub const MAX_TEXT_LENGTH: usize = 1024;

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TextError {
    pub error_code: String,
    pub message: String,
    pub request_id: Option<String>,
}

impl TextError {
    pub fn local(code: &str, message: &str) -> Self {
        Self {
            error_code: code.into(),
            message: message.into(),
            request_id: None,
        }
    }

    pub fn contract() -> Self {
        Self::local("IPC_CONTRACT_ERROR", "Backend yanıtı doğrulanamadı.")
    }
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Intent {
    Greeting,
    Arithmetic,
    ActionRequest,
    GeneralChat,
    Unknown,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionOperation {
    OpenApplication,
    SearchFiles,
    WebSearch,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ActionClassification {
    pub operation: ActionOperation,
    pub target: String,
    pub executable: bool,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArithmeticResult {
    pub expression: String,
    pub value: String,
    pub rounded: bool,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TextReply {
    pub api_version: String,
    pub original_text: String,
    pub normalized_text: String,
    pub intent: Intent,
    pub reply: String,
    pub action: Option<ActionClassification>,
    pub arithmetic: Option<ArithmeticResult>,
    pub external_calls: u8,
}

impl TextReply {
    pub fn validate(self, original: &str) -> Result<Self, TextError> {
        if self.api_version != "1"
            || self.original_text != original
            || self.external_calls != 0
            || self.original_text.chars().count() > MAX_TEXT_LENGTH
            || self.normalized_text.is_empty()
            || self.normalized_text.chars().count() > MAX_TEXT_LENGTH
            || self.reply.is_empty()
            || self.reply.chars().count() > 512
            || (self.intent == Intent::ActionRequest) != self.action.is_some()
            || (self.intent == Intent::Arithmetic) != self.arithmetic.is_some()
            || self.action.as_ref().is_some_and(|a| {
                a.executable || a.target.is_empty() || a.target.chars().count() > MAX_TEXT_LENGTH
            })
            || self
                .arithmetic
                .as_ref()
                .is_some_and(|a| a.expression.chars().count() > 256 || a.value.len() > 24)
        {
            return Err(TextError::contract());
        }
        Ok(self)
    }
}

pub fn validate_input(text: &str) -> Result<(), TextError> {
    if text.chars().count() > MAX_TEXT_LENGTH {
        return Err(TextError::local(
            "TEXT_TOO_LONG",
            "Mesaj en fazla 1.024 karakter olabilir.",
        ));
    }
    if text.trim().is_empty() {
        return Err(TextError::local("TEXT_EMPTY", "Mesaj boş olamaz."));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn action_reply() -> serde_json::Value {
        serde_json::json!({"api_version":"1","original_text":"Chrome'u aç","normalized_text":"Chrome'u aç",
            "intent":"action_request","reply":"Bu aşamada çalıştırmıyorum.","external_calls":0,
            "action":{"operation":"open_application","target":"Chrome","executable":false},"arithmetic":null})
    }

    #[test]
    fn unicode_limits_count_scalars_and_empty_is_rejected() {
        assert!(validate_input(&"😀".repeat(1024)).is_ok());
        assert_eq!(
            validate_input(&"😀".repeat(1025)).unwrap_err().error_code,
            "TEXT_TOO_LONG"
        );
        assert_eq!(
            validate_input(" \n\t").unwrap_err().error_code,
            "TEXT_EMPTY"
        );
    }

    #[test]
    fn action_metadata_cannot_claim_execution_or_cloud_calls() {
        let reply: TextReply = serde_json::from_value(action_reply()).unwrap();
        assert!(reply.validate("Chrome'u aç").is_ok());
        for field in ["executable", "external_calls", "intent", "original_text"] {
            let mut value = action_reply();
            match field {
                "executable" => value["action"][field] = serde_json::json!(true),
                "external_calls" => value[field] = serde_json::json!(1),
                "intent" => value[field] = serde_json::json!("general_chat"),
                _ => value[field] = serde_json::json!("altered"),
            }
            let reply: TextReply = serde_json::from_value(value).unwrap();
            assert!(reply.validate("Chrome'u aç").is_err());
        }
        let mut value = action_reply();
        value["token"] = serde_json::json!("unexpected");
        assert!(serde_json::from_value::<TextReply>(value).is_err());
    }
}
