/** Human-readable labels for the token flows the integration service uses. */
export const TOKEN_FLOW_LABELS = {
	none: "No bank token",
	"token-generation": "Token Generation",
	"token-generation-internal": "Token Generation (server-side)",
	"bank-auth": "Bank Auth",
	"bank-auth-internal": "Bank Auth (server-side)",
};

/** Rendered value for any redacted field. */
export const SECRET_MASK = "********";

/**
 * Mirrors the backend's request-body redaction (and the integration service's
 * mask_sensitive_data) so response bodies are redacted on screen too.
 *
 * Applied at render time only: the browser legitimately has to hold the raw
 * access_token so it can chain it into the next call.
 */
const SENSITIVE_KEYS = [
	"secretkey",
	"clientid",
	"clientsecret",
	"secret",
	"password",
	"username",
	"accesstoken",
	"access_token",
	"token",
	"apikey",
	"api_key",
];

/**
 * A three-segment base64url blob is a JWT whatever key it sits under.
 *
 * Key-based masking alone is not enough: a token parked under a neutral key
 * ({"value": "eyJ..."}) or quoted inside a validation error would otherwise
 * render in full. Matching is substring-based so a JWT embedded in a message
 * is redacted too.
 */
const JWT_PATTERN = /[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g;

export const maskSecrets = (value) => {
	if (Array.isArray(value)) return value.map(maskSecrets);

	if (value && typeof value === "object") {
		return Object.fromEntries(
			Object.entries(value).map(([key, item]) => [
				key,
				SENSITIVE_KEYS.some((marker) => key.toLowerCase().includes(marker))
					? SECRET_MASK
					: maskSecrets(item),
			]),
		);
	}

	if (typeof value === "string" && JWT_PATTERN.test(value)) {
		JWT_PATTERN.lastIndex = 0;
		return value.replace(JWT_PATTERN, SECRET_MASK);
	}
	JWT_PATTERN.lastIndex = 0;

	return value;
};

export default { TOKEN_FLOW_LABELS, SECRET_MASK, maskSecrets };