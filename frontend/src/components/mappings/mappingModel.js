export const METHOD_OPTIONS = ["GET", "POST", "PUT", "DELETE", "PATCH"];

export const PARAM_TYPE_OPTIONS = ["BODY", "HEADER", "QUERY"];

export const DATA_TYPE_OPTIONS = [
	"STRING",
	"INTEGER",
	"BOOLEAN",
	"DATE",
	"FLOAT",
	"JSON",
];

export const PARAM_TYPE_COLORS = {
	BODY: "#1976d2",
	HEADER: "#9c27b0",
	QUERY: "#00897b",
};

let rowSequence = 0;

export function createMappingRow(overrides = {}) {
	rowSequence += 1;
	return {
		id: `map-${Date.now().toString(36)}-${rowSequence}-${Math.random().toString(36).slice(2, 7)}`,
		sourceField: "",
		targetField: "",
		parameterType: "BODY",
		dataType: "STRING",
		enabled: true,
		...overrides,
	};
}

function normalizeParamType(value) {
	const raw = String(value ?? "")
		.trim()
		.toUpperCase();
	if (PARAM_TYPE_OPTIONS.includes(raw)) return raw;

	if (raw === "QUERYSTRING" || raw === "QUERY_STRING") return "QUERY";
	return "BODY";
}

function normalizeDataType(value) {
	const raw = String(value ?? "")
		.trim()
		.toUpperCase();
	return DATA_TYPE_OPTIONS.includes(raw) ? raw : "STRING";
}

export function parametersToRows(parameters = []) {
	return (Array.isArray(parameters) ? parameters : []).map((parameter) => {
		const row = createMappingRow({
			sourceField: String(
				parameter?.source_parameter ?? parameter?.sourceField ?? "",
			),
			targetField: String(
				parameter?.target_parameter ?? parameter?.targetField ?? "",
			),
			parameterType: normalizeParamType(
				parameter?.parameter_type ?? parameter?.parameterType,
			),
			dataType: normalizeDataType(parameter?.data_type ?? parameter?.dataType),
			enabled: parameter?.is_active ?? parameter?.enabled ?? true,
		});
		if (parameter?.id != null) row.id = `param-${parameter.id}`;
		return row;
	});
}

export function isSftpForm(form = {}) {
	return (
		String(form.protocol ?? "HTTP")
			.trim()
			.toUpperCase() === "SFTP"
	);
}

export function validateMappingForm(form = {}, mappings = []) {
	const errors = {};
	// `sourceUrl` is the external API (the upstream the gateway actually
	// calls) and `targetUrl` the internal route; see gateway_engine.
	const sourceUrl = String(form.sourceUrl ?? "").trim();
	const targetUrl = String(form.targetUrl ?? "").trim();
	const sftp = isSftpForm(form);

	if (!targetUrl) errors.targetUrl = "Internal URL is required.";
	if (!sftp && !sourceUrl) errors.sourceUrl = "External URL is required.";
	if (!METHOD_OPTIONS.includes(form.sourceMethod))
		errors.sourceMethod = "Pick an internal method.";
	if (!METHOD_OPTIONS.includes(form.targetMethod))
		errors.targetMethod = "Pick an external method.";

	if (sftp) {
		// The gateway only treats a target as SFTP-backed when it is a plain
		// route path (``/v1/audio/play``), not an absolute HTTP URL.
		if (targetUrl && /^[a-z][a-z0-9+.-]*:\/\//i.test(targetUrl)) {
			errors.targetUrl =
				"SFTP mappings serve a gateway path — remove the http(s):// prefix.";
		}
		if (!String(form.sftpHost ?? "").trim()) {
			errors.sftpHost = "SFTP host is required.";
		}
		const port = Number(form.sftpPort || 22);
		if (!Number.isInteger(port) || port < 1 || port > 65535) {
			errors.sftpPort = "Port must be between 1 and 65535.";
		}
		if (!String(form.sftpRemotePath ?? "").trim()) {
			errors.sftpRemotePath = "Remote path is required.";
		}
	}

	const activeRows = mappings.filter(
		(row) => row.enabled && (row.sourceField.trim() || row.targetField.trim()),
	);

	if (activeRows.length === 0) {
		errors.mappings =
			"Add at least one enabled mapping with both fields filled in.";
	} else if (
		activeRows.some((row) => !row.sourceField.trim() || !row.targetField.trim())
	) {
		errors.mappings =
			"Every enabled row needs both an internal and an external field.";
	}

	return { valid: Object.keys(errors).length === 0, errors };
}

export function buildAutoDescription(form = {}, mappings = []) {
	const { sourceUrl, sourceMethod, targetUrl, targetMethod } = form;
	if (!String(sourceUrl ?? "").trim() && !String(targetUrl ?? "").trim())
		return "";

	const filled = mappings.filter(
		(row) => row.sourceField.trim() || row.targetField.trim(),
	);
	const enabled = filled.filter((row) => row.enabled);

	// Rendered inbound -> outbound, the way the request actually flows.
	const remote = isSftpForm(form)
		? `SFTP ${String(form.sftpHost ?? "").trim() || "…"}:${
				String(form.sftpPort ?? "").trim() || "22"
			}${String(form.sftpRemotePath ?? "").trim() || "/"}`
		: `${targetMethod || "—"} ${String(sourceUrl ?? "").trim() || "…"}`;
	const route = `${sourceMethod || "—"} ${
		String(targetUrl ?? "").trim() || "…"
	} → ${remote}`;

	if (enabled.length === 0) return `${route} — no enabled field mappings yet`;

	const breakdown = enabled.reduce((acc, row) => {
		acc[row.parameterType] = (acc[row.parameterType] || 0) + 1;
		return acc;
	}, {});
	const parts = Object.entries(breakdown).map(
		([type, count]) => `${type} × ${count}`,
	);

	return `${route} — ${enabled.length} mapped field${enabled.length === 1 ? "" : "s"}${
		parts.length ? ` (${parts.join(", ")})` : ""
	}`;
}

export function buildCompleteMappingPayload({
	form = {},
	authEnabled = false,
	auth = {},
	mappings = [],
}) {
	const clean = (value) => {
		const text = String(value ?? "").trim();
		return text ? text : null;
	};

	const sftp = isSftpForm(form);
	const targetUrl = String(form.targetUrl ?? "").trim();

	return {
		// SFTP mappings have no HTTP upstream: the same gateway path is kept
		// in ``sourceUrl`` so the API contract stays non-null (and the audio
		// endpoints remain addressable by route + method).
		sourceUrl: sftp ? targetUrl : String(form.sourceUrl ?? "").trim(),
		targetUrl,
		sourceMethod: form.sourceMethod,
		// SFTP has no HTTP upstream: both verbs describe the same gateway
		// route, and the backend stores ``targetMethod`` as the route verb.
		targetMethod: sftp ? form.sourceMethod : form.targetMethod,
		protocol: sftp ? "SFTP" : "HTTP",
		mappings: mappings
			.filter((row) => row.sourceField.trim() || row.targetField.trim())
			.map((row) => ({
				sourceField: row.sourceField.trim(),
				targetField: row.targetField.trim(),
				enabled: Boolean(row.enabled),
				parameterType: row.parameterType,
				parameterTypeValue: row.parameterType,
			})),
		api_id: !sftp && authEnabled ? clean(auth.apiId) : null,
		api_password: !sftp && authEnabled ? clean(auth.apiPassword) : null,
		api_auth_url: !sftp && authEnabled ? clean(auth.apiAuthUrl) : null,
		sftp_host: sftp ? clean(form.sftpHost) : null,
		sftp_port: sftp ? Number(form.sftpPort) || 22 : null,
		sftp_username: sftp ? clean(form.sftpUsername) : null,
		// A blank password on edit leaves the stored secret untouched.
		sftp_password: sftp ? clean(form.sftpPassword) : null,
		sftp_private_key_path: sftp ? clean(form.sftpPrivateKeyPath) : null,
		sftp_remote_path: sftp ? clean(form.sftpRemotePath) : null,
		dynamic_filename_pattern: sftp
			? clean(form.dynamicFilenamePattern)
			: null,
	};
}
