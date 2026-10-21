import api from "./api";

export const getVariables = async (unmask = false) => {
	const response = await api.get("/variables", { params: { unmask } });
	return response.data?.data || [];
};

export const saveVariable = async (data) => {
	const response = await api.post("/variables", data);
	return response.data;
};

export const deleteVariable = async (id) => {
	const response = await api.delete(`/variables/${id}`);
	return response.data;
};

export default {
	getVariables,
	saveVariable,
	deleteVariable,
};
