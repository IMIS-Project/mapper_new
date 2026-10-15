/** Standard HTTP status text, shared by the response viewers. */
export const STATUS_TEXT = {
	200: "OK",
	201: "Created",
	202: "Accepted",
	204: "No Content",
	301: "Moved Permanently",
	302: "Found",
	304: "Not Modified",
	400: "Bad Request",
	401: "Unauthorized",
	403: "Forbidden",
	404: "Not Found",
	405: "Method Not Allowed",
	408: "Request Timeout",
	409: "Conflict",
	415: "Unsupported Media Type",
	422: "Unprocessable Entity",
	429: "Too Many Requests",
	500: "Internal Server Error",
	502: "Bad Gateway",
	503: "Service Unavailable",
	504: "Gateway Timeout",
};

/** Text for a status code, falling back to a family label. */
export function statusLabel(code) {
	if (code == null) return "No status";
	if (STATUS_TEXT[code]) return STATUS_TEXT[code];
	if (code >= 200 && code < 300) return "Success";
	if (code >= 300 && code < 400) return "Redirect";
	if (code >= 400 && code < 500) return "Client error";
	if (code >= 500) return "Server error";
	return "Unknown";
}

/** Colour plus label for a status code, for the status chips. */
export function statusTone(code, palette) {
	if (code == null) return { color: palette.text.disabled, label: "No status" };
	if (code >= 200 && code < 300)
		return { color: palette.success.main, label: statusLabel(code) };
	if (code >= 300 && code < 400)
		return { color: palette.info.main, label: statusLabel(code) };
	if (code >= 400 && code < 500)
		return { color: palette.warning.main, label: statusLabel(code) };
	if (code >= 500)
		return { color: palette.error.main, label: statusLabel(code) };
	return { color: palette.text.secondary, label: "Unknown" };
}

export default { STATUS_TEXT, statusLabel, statusTone };