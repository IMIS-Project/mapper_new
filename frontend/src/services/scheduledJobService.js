import api from "./api";

export const getScheduledJobs = async () => {
	const response = await api.get("/scheduled-jobs");
	return response.data;
};

export const getScheduledJobRuns = async (jobId, limit = 100) => {
	const response = await api.get(`/scheduled-jobs/${jobId}/runs`, {
		params: { limit },
	});
	return response.data;
};

export const getScheduledRuns = async (limit = 100) => {
	const response = await api.get("/scheduled-runs", { params: { limit } });
	return response.data;
};

export const getScheduledRunDetail = async (runId) => {
	const response = await api.get(`/scheduled-runs/${runId}`);
	return response.data;
};

export const createScheduledJob = async (data) => {
	const response = await api.post("/scheduled-jobs", data);
	return response.data;
};

export const toggleScheduledJob = async (jobId, enabled) => {
	const response = await api.patch(`/scheduled-jobs/${jobId}`, { enabled });
	return response.data;
};

export const updateScheduledJob = async (jobId, data) => {
	const response = await api.put(`/scheduled-jobs/${jobId}`, data);
	return response.data;
};

export const deleteScheduledJob = async (jobId) => {
	const response = await api.delete(`/scheduled-jobs/${jobId}`);
	return response.data;
};

export const runScheduledJob = async (jobId) => {
	const response = await api.post(`/scheduled-jobs/${jobId}/run`);
	return response.data;
};

export default {
	getScheduledJobs,
	getScheduledJobRuns,
	getScheduledRuns,
	getScheduledRunDetail,
	createScheduledJob,
	toggleScheduledJob,
	updateScheduledJob,
	deleteScheduledJob,
	runScheduledJob,
};
