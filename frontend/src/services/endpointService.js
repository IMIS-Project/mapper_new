import api from "./api";

export const getEndpoints = async () => {
	const response = await api.get("/api-endpoints");
	return response.data;
};

export const getEndpoint = async (id) => {
	const response = await api.get(`/api-endpoints/${id}`);
	return response.data;
};

export const getParameters = async (endpointId) => {
	const response = await api.get(`/api-endpoints/${endpointId}/parameters`);
	return response.data;
};

/**
 * Read-only listing used by the cron job picker. The scheduler screen never
 * writes to the mapping database, so this is a plain SELECT.
 */
export const listMappings = async (search) => {
	// React Query passes its query context to the query function. Only an
	// explicit string is a real search term; never serialize that context into
	// API query parameters.
	const term = typeof search === "string" ? search.trim() : "";
	const response = await api.get("/api-endpoints", {
		params: { limit: 500, ...(term ? { search: term } : {}) },
	});
	return response.data;
};

export const saveCompleteMapping = async (data) => {
	const response = await api.post("/mappings/complete", data);
	return response.data;
};

export const updateCompleteMapping = async (id, data) => {
	const response = await api.put(`/mappings/complete/${id}`, data);
	return response.data;
};

export const deleteEndpoint = async (id) => {
	const response = await api.delete(`/api-endpoints/${id}`);
	return response.data;
};

export const updateEndpoint = async (id, data) => {
	const response = await api.patch(`/api-endpoints/${id}`, data);
	return response.data;
};

export default {
	getEndpoints,
	getEndpoint,
	getParameters,
	listMappings,
	saveCompleteMapping,
	updateCompleteMapping,
	deleteEndpoint,
	updateEndpoint,
};
