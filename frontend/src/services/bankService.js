import api from "./api";

/** Catalog of the allow-listed bank operations and their token flows. */
export const getBankOperations = async () => {
	const response = await api.get("/bank/operations");
	return response.data;
};

/** Non-secret wiring (integration base URL, whether a token is configured). */
export const getBankConfig = async () => {
	const response = await api.get("/bank/config");
	return response.data;
};

/** Forward one operation to the integration service. */
export const callBankOperation = async (data) => {
	const response = await api.post("/bank/call", data, { timeout: 120000 });
	return response.data;
};

/**
 * Pull the token out of a token endpoint response.
 *
 * The two flows return it in different shapes:
 *   - Token Generation -> `{ access_token }`
 *   - Bank Auth        -> `{ ResponseDescription: { AccessToken, ExpiresIn } }`
 */
export const extractBankToken = (operation, data) => {
	if (!operation?.tokenOutcome || !data) return null;

	const path = String(operation.tokenOutcome).split(".");
	let current = data;
	for (const segment of path) {
		if (current == null || typeof current !== "object") return null;
		current = current[segment];
	}

	const value = typeof current === "string" ? current.trim() : "";
	return value || null;
};

/** Bank Auth reports a relative expiry; normalise it to an absolute epoch (s). */
export const extractTokenExpiry = (operation, data) => {
	if (!data || typeof data !== "object") return null;
	const expiresIn = Number(data?.ResponseDescription?.ExpiresIn);
	if (!Number.isFinite(expiresIn) || expiresIn <= 0) return null;
	return Math.floor(Date.now() / 1000) + expiresIn;
};

export default {
	getBankOperations,
	getBankConfig,
	callBankOperation,
	extractBankToken,
	extractTokenExpiry,
};