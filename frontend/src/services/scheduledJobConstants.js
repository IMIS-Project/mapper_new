const toDate = (value) => {
	if (!value) return null;
	const date = value instanceof Date ? value : new Date(value);
	return Number.isNaN(date.getTime()) ? null : date;
};

export const formatDate = (value) => {
	const date = toDate(value);
	if (!date) return value ? String(value) : "—";
	return date.toLocaleString([], {
		year: "numeric",
		month: "short",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
	});
};

/**
 * Full timestamp down to the second, for run history where the exact
 * execution time is the point.
 */
export const formatExactTime = (value) => {
	const date = toDate(value);
	if (!date) return value ? String(value) : "—";
	return date.toLocaleString([], {
		year: "numeric",
		month: "short",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
		hour12: false,
	});
};

/** Millisecond precision plus an explicit UTC marker, for the detail view. */
export const formatPreciseTime = (value) => {
	const date = toDate(value);
	if (!date) return value ? String(value) : "—";
	const iso = date.toISOString();
	return `${iso.slice(0, 10)} ${iso.slice(11, 19)}.${iso.slice(20, 23)} UTC`;
};

/** Coarse "how long ago" label, e.g. "just now", "12m ago", "3d ago". */
export const formatRelative = (value) => {
	const date = toDate(value);
	if (!date) return "—";
	const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
	if (seconds < 45) return "just now";
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 30) return `${days}d ago`;
	return date.toLocaleDateString();
};

export const formatDuration = (value) => {
	if (value === null || value === undefined) return "—";
	if (value < 1000) return `${value} ms`;
	return `${(value / 1000).toFixed(2)} s`;
};

export const scheduleLabel = (job) => {
	if (!job) return "—";
	if (job.cron) return `Cron · ${job.cron}`;
	if (job.interval_seconds) return `Every ${formatDuration(job.interval_seconds * 1000)}`;
	return "—";
};

export const getErrorMessage = (error, fallback = "Something went wrong.") => {
	const detail = error?.response?.data?.detail;
	if (Array.isArray(detail)) {
		return detail.map((item) => item?.msg || JSON.stringify(item)).join("; ") || fallback;
	}
	if (typeof detail === "string") return detail;
	if (detail) return JSON.stringify(detail);
	return error?.message || fallback;
};

export const METHODS = [
	"GET",
	"POST",
	"PUT",
	"PATCH",
	"DELETE",
	"HEAD",
	"OPTIONS",
];

/** Methods the backend accepts a body for. */
export const METHODS_WITH_BODY = ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"];

export const supportsBody = (method) => METHODS_WITH_BODY.includes(method);

export const formatBytes = (value) => {
	if (value === null || value === undefined) return "—";
	if (value < 1024) return `${value} B`;
	if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
	return `${(value / (1024 * 1024)).toFixed(1)} MB`;
};

/** Turn `{ "A": "b" }` into the `[{ name, value }]` rows the form edits. */
export const headersToRows = (headers) =>
	Object.entries(headers || {}).map(([name, value]) => ({ name, value }));

/** Turn form rows back into an object, dropping blank names. */
export const rowsToHeaders = (rows) => {
	const headers = {};
	(rows || []).forEach((row) => {
		const name = (row.name || "").trim();
		if (name) headers[name] = (row.value || "").trim();
	});
	return headers;
};

/** Pretty-print a body when it parses as JSON, otherwise show it verbatim. */
export const formatBody = (body) => {
	if (body === null || body === undefined || body === "") return "";
	try {
		return JSON.stringify(JSON.parse(body), null, 2);
	} catch {
		return body;
	}
};

/* ------------------------------------------------------------------ *
 * API mapping helpers (read-only view of `api_endpoint` +
 * `api_endpoint_parameter_mapping`).
 *
 * Direction follows the gateway runtime, the same convention the endpoints
 * page shows with its outbound/inbound icons:
 *   source_api_url  -> the EXTERNAL API, the upstream actually dialled
 *   target_api_url  -> the INTERNAL API, the route that receives the payload
 * A mapping-backed job always calls the external API first and forwards its
 * response verbatim to the internal API.
 * ------------------------------------------------------------------ */

/** Marks a run body written as the two-leg mapping envelope. */
export const MAPPING_RUN_KIND = "api-mapping-cron-run";

/** How a mapped parameter travels on the target request. */
export const PARAM_LOCATIONS = ["BODY", "HEADER", "QUERY"];

/** Legacy rows spell the query location "QUERYSTRING" (or "QUERY_STRING"). */
const PARAM_LOCATION_ALIASES = {
	QUERYSTRING: "QUERY",
	QUERY_STRING: "QUERY",
};

/** Normalise the mapping's `method` to one the scheduler accepts. */
export const MAPPING_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

export const normalizeMappingMethod = (method, fallback = "POST") => {
	const normalized = String(method || "").trim().toUpperCase();
	return MAPPING_METHODS.includes(normalized) ? normalized : fallback;
};

/** The external (upstream) API of a mapping — the one always called first. */
export const mappingExternalUrl = (mapping) =>
	String(mapping?.source_api_url || "").trim();

/** The internal API of a mapping — the one that receives the external payload. */
export const mappingInternalUrl = (mapping) =>
	String(mapping?.target_api_url || "").trim();

/** An internal URL must be absolute for the payload to be delivered to it. */
export const isAbsoluteHttpUrl = (url) =>
	/^https?:\/\//i.test(String(url || "").trim());

/** Split a mapping's parameter rows into their BODY/HEADER/QUERY buckets. */
export const groupParametersByLocation = (parameters) => {
	const groups = { BODY: [], HEADER: [], QUERY: [] };
	(parameters || []).forEach((parameter) => {
		if (parameter?.is_active === false) return;
		const raw = String(parameter?.parameter_type || "BODY").trim().toUpperCase();
		const normalized = PARAM_LOCATION_ALIASES[raw] || raw;
		const location = PARAM_LOCATIONS.includes(normalized) ? normalized : "BODY";
		groups[location].push(parameter);
	});
	return groups;
};

/**
 * The name the cron job's own request carries for a parameter. The gateway
 * reads inbound values by `target_parameter` and renames them to
 * `source_parameter` on the way out to the external API.
 */
export const parameterInternalName = (parameter) =>
	String(parameter?.target_parameter || "").trim();

/** The name the same parameter takes on the external API. */
export const parameterExternalName = (parameter) =>
	String(parameter?.source_parameter || "").trim();

/** `{ name, value }` rows seeded from a bucket of mapped parameters. */
export const parametersToRows = (parameters) =>
	(parameters || [])
		.map((parameter) => ({ name: parameterInternalName(parameter), value: "" }))
		.filter((row) => row.name);

/** A JSON body skeleton keyed by the internal field names. */
export const buildBodySkeleton = (parameters) => {
	const names = (parameters || []).map(parameterInternalName).filter(Boolean);
	if (!names.length) return "";
	return `${JSON.stringify(
		Object.fromEntries(names.map((name) => [name, ""])),
		null,
		2,
	)}\n`;
};

/** Merge freshly mapped rows into the rows already on the form. */
export const mergeRows = (existing, incoming) => {
	const merged = [...(existing || [])];
	(incoming || []).forEach((row) => {
		const name = (row?.name || "").trim();
		if (!name) return;
		const position = merged.findIndex(
			(item) => (item.name || "").trim().toLowerCase() === name.toLowerCase(),
		);
		if (position === -1) merged.push({ ...row });
	});
	return merged;
};

/**
 * The two-leg envelope a mapping run stores, or `null` for a plain run whose
 * body is just the upstream response.
 */
export const parseMappingRun = (run) => {
	if (!run?.response_body) return null;
	try {
		const parsed = JSON.parse(run.response_body);
		if (parsed && parsed.kind === MAPPING_RUN_KIND) return parsed;
	} catch {
		/* A plain body that is not JSON is not a mapping run. */
	}
	return null;
};

/** Pretty-print one leg's captured body for the run detail view. */
export const formatLegBody = (leg) => {
	const body = leg?.body;
	if (body === null || body === undefined || body === "") return "";
	if (typeof body === "string") return formatBody(body);
	return JSON.stringify(body, null, 2);
};

export const initialJobForm = {
	job_id: "",
	name: "",
	url: "",
	method: "GET",
	scheduleType: "interval",
	intervalSeconds: "60",
	cron: "*/5 * * * *",
	headers: [],
	body: "",
	/** "manual" keeps the free-text URL box; "mapping" registers from a mapping. */
	sourceMode: "manual",
	/** Id of the selected API mapping, when registering from one. */
	mappingId: null,
};
