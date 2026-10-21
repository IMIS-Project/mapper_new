import api from "./api";

export const getWorkflows = async () => {
	const response = await api.get("/workflows");
	return response.data?.data || [];
};

export const getWorkflow = async (id) => {
	const response = await api.get(`/workflows/${id}`);
	return response.data?.data || null;
};

export const createWorkflow = async (data) => {
	const response = await api.post("/workflows", data);
	return response.data;
};

export const updateWorkflow = async (id, data) => {
	const response = await api.put(`/workflows/${id}`, data);
	return response.data;
};

export const deleteWorkflow = async (id) => {
	const response = await api.delete(`/workflows/${id}`);
	return response.data;
};

export const addStep = async (workflowId, stepData) => {
	const response = await api.post(`/workflows/${workflowId}/steps`, stepData);
	return response.data;
};

export const updateStep = async (workflowId, stepId, stepData) => {
	const response = await api.put(`/workflows/${workflowId}/steps/${stepId}`, stepData);
	return response.data;
};

export const deleteStep = async (workflowId, stepId) => {
	const response = await api.delete(`/workflows/${workflowId}/steps/${stepId}`);
	return response.data;
};

export const reorderSteps = async (workflowId, steps) => {
	const response = await api.put(`/workflows/${workflowId}/steps/reorder`, { steps });
	return response.data;
};

export const runWorkflow = async (workflowId, triggerPayload = {}) => {
	const response = await api.post(`/workflows/${workflowId}/run`, {
		trigger_payload: triggerPayload,
	});
	return response.data?.data;
};

export const testStep = async (workflowId, stepId, context = {}, config = null, stepType = null) => {
	const response = await api.post(`/workflows/${workflowId}/steps/${stepId}/test`, {
		context,
		config,
		step_type: stepType,
	});
	return response.data?.data;
};

export const getWorkflowRuns = async (workflowId, limit = 50) => {
	const response = await api.get(`/workflows/${workflowId}/runs`, {
		params: { limit },
	});
	return response.data?.data || [];
};

export const parseCurl = async (curlCommand) => {
	const response = await api.post("/workflows/parse-curl", {
		curl_command: curlCommand,
	});
	return response.data?.data;
};

export default {
	getWorkflows,
	getWorkflow,
	createWorkflow,
	updateWorkflow,
	deleteWorkflow,
	addStep,
	updateStep,
	deleteStep,
	reorderSteps,
	runWorkflow,
	testStep,
	getWorkflowRuns,
	parseCurl,
};

