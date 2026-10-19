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

export function validateMappingForm(form = {}, mappings = []) {
	const errors = {};
	// `sourceUrl` is the external API (the upstream the gateway actually
	// calls) and `targetUrl` the internal route; see gateway_engine.
	const sourceUrl = String(form.sourceUrl ?? "").trim();
	const targetUrl = String(form.targetUrl ?? "").trim();

	if (!targetUrl) errors.targetUrl = "Internal URL is required.";
	if (!sourceUrl) errors.sourceUrl = "External URL is required.";
	if (!METHOD_OPTIONS.includes(form.sourceMethod))
		errors.sourceMethod = "Pick an internal method.";
	if (!METHOD_OPTIONS.includes(form.targetMethod))
		errors.targetMethod = "Pick an external method.";

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
	const route = `${sourceMethod || "—"} ${String(targetUrl ?? "").trim() || "…"} → ${
		targetMethod || "—"
	} ${String(sourceUrl ?? "").trim() || "…"}`;

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

	return {
		sourceUrl: String(form.sourceUrl ?? "").trim(),
		targetUrl: String(form.targetUrl ?? "").trim(),
		sourceMethod: form.sourceMethod,
		targetMethod: form.targetMethod,
		mappings: mappings
			.filter((row) => row.sourceField.trim() || row.targetField.trim())
			.map((row) => ({
				sourceField: row.sourceField.trim(),
				targetField: row.targetField.trim(),
				enabled: Boolean(row.enabled),
				parameterType: row.parameterType,
				parameterTypeValue: row.parameterType,
			})),
		api_id: authEnabled ? clean(auth.apiId) : null,
		api_password: authEnabled ? clean(auth.apiPassword) : null,
		api_auth_url: authEnabled ? clean(auth.apiAuthUrl) : null,
	};
}
