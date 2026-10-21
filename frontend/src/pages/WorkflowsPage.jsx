import {
	AccountTree,
	Add,
	CheckCircleOutline,
	DeleteOutline,
	EditOutlined,
	ErrorOutline,
	PlayArrow,
	Refresh,
	Schedule,
	TrendingFlat,
} from "@mui/icons-material";
import {
	Alert,
	Box,
	Button,
	Card,
	CardContent,
	Chip,
	CircularProgress,
	Dialog,
	DialogActions,
	DialogContent,
	DialogTitle,
	Divider,
	Grid,
	IconButton,
	Paper,
	Stack,
	Switch,
	TextField,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSnackbar } from "../context/SnackbarContext";
import workflowService from "../services/workflowService";

export default function WorkflowsPage() {
	const theme = useTheme();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { showSuccess, showError } = useSnackbar();

	const [createOpen, setCreateOpen] = useState(false);
	const [createForm, setCreateForm] = useState({
		name: "",
		slug: "",
		description: "",
		trigger_type: "manual",
	});

	const [runOpen, setRunOpen] = useState(false);
	const [activeWorkflow, setActiveWorkflow] = useState(null);
	const [triggerPayloadInput, setTriggerPayloadInput] = useState("{}");
	const [runResult, setRunResult] = useState(null);

	const { data: workflows = [], isLoading, isFetching, refetch } = useQuery({
		queryKey: ["workflows"],
		queryFn: workflowService.getWorkflows,
	});

	const createMutation = useMutation({
		mutationFn: (data) => workflowService.createWorkflow(data),
		onSuccess: (res) => {
			showSuccess("Workflow created");
			queryClient.invalidateQueries({ queryKey: ["workflows"] });
			setCreateOpen(false);
			if (res.data?.id) {
				navigate(`/workflows/${res.data.id}`);
			}
		},
		onError: (err) => {
			showError(err.response?.data?.detail || err.message || "Failed to create workflow");
		},
	});

	const deleteMutation = useMutation({
		mutationFn: (id) => workflowService.deleteWorkflow(id),
		onSuccess: () => {
			showSuccess("Workflow deleted");
			queryClient.invalidateQueries({ queryKey: ["workflows"] });
		},
		onError: (err) => {
			showError(err.response?.data?.detail || err.message || "Failed to delete workflow");
		},
	});

	const toggleActiveMutation = useMutation({
		mutationFn: ({ id, is_active }) => workflowService.updateWorkflow(id, { is_active }),
		onMutate: async ({ id, is_active }) => {
			await queryClient.cancelQueries({ queryKey: ["workflows"] });
			const previous = queryClient.getQueryData(["workflows"]);
			queryClient.setQueryData(["workflows"], (old) => {
				if (!Array.isArray(old)) return old;
				return old.map((wf) => (wf.id === id ? { ...wf, is_active } : wf));
			});
			return { previous };
		},
		onError: (err, _vars, context) => {
			if (context?.previous) {
				queryClient.setQueryData(["workflows"], context.previous);
			}
			showError(err.response?.data?.detail?.message || err.response?.data?.detail || err.message || "Failed to update workflow");
		},
		onSuccess: (_, vars) => {
			showSuccess(
				vars.is_active
					? "Workflow is now LIVE! Webhook listener is actively listening."
					: "Workflow paused (Inactive). Webhook listener paused."
			);
		},
		onSettled: () => {
			queryClient.invalidateQueries({ queryKey: ["workflows"] });
		},
	});

	const runMutation = useMutation({
		mutationFn: ({ id, payload }) => workflowService.runWorkflow(id, payload),
		onSuccess: (data) => {
			setRunResult(data);
			queryClient.invalidateQueries({ queryKey: ["workflows"] });
			if (data?.status === "SUCCESS") {
				showSuccess(`Workflow completed in ${data.total_time_ms}ms`);
			} else {
				showError(`Workflow execution failed: ${data?.error || "Unknown error"}`);
			}
		},
		onError: (err) => {
			showError(err.response?.data?.detail?.message || err.message || "Run failed");
		},
	});

	const handleOpenRun = (wf) => {
		setActiveWorkflow(wf);
		setRunResult(null);
		setTriggerPayloadInput("{\n  \"source_ticket_id\": \"IMIS-TICKET-2026-00123\",\n  \"benef_cnic\": \"42201-1234567-1\",\n  \"category\": \"Payments\",\n  \"subcategory\": \"Delayed Transfer\",\n  \"complaint_type\": \"benef\",\n  \"complainant_name\": \"Fatima Bibi\",\n  \"complainant_phone\": \"03001234567\",\n  \"description\": \"Beneficiary did not receive the scheduled installment.\",\n  \"notes\": \"Received via IMIS Call Center\",\n  \"program_id\": 1\n}");
		setRunOpen(true);
	};

	const handleExecuteRun = () => {
		let parsed = {};
		try {
			if (triggerPayloadInput.trim()) {
				parsed = JSON.parse(triggerPayloadInput);
			}
		} catch (e) {
			showError("Invalid JSON in trigger payload");
			return;
		}
		runMutation.mutate({ id: activeWorkflow.id, payload: parsed });
	};

	return (
		<Box sx={{ pb: 6 }}>
			{/* Page Header */}
			<Stack
				direction={{ xs: "column", sm: "row" }}
				justifyContent="space-between"
				alignItems={{ xs: "flex-start", sm: "center" }}
				gap={2}
				sx={{ mb: 3 }}
			>
				<Box>
					<Typography variant="h5" fontWeight={700} sx={{ display: "flex", alignItems: "center", gap: 1 }}>
						<AccountTree color="primary" /> Workflows & Pipelines
					</Typography>
					<Typography variant="body2" color="text.secondary">
						Orchestrate multi-step integration flows: Triggers, AES-256-GCM symmetric encryption, authenticated HTTP requests, and data transformations.
					</Typography>
				</Box>

				<Stack direction="row" spacing={1.5} alignItems="center">
					<Button
						variant="outlined"
						size="small"
						startIcon={isFetching ? <CircularProgress size={16} /> : <Refresh />}
						onClick={() => refetch()}
					>
						Refresh
					</Button>
					<Button
						variant="contained"
						size="small"
						startIcon={<Add />}
						onClick={() => {
							setCreateForm({
								name: "",
								slug: "",
								description: "",
								trigger_type: "webhook",
							});
							setCreateOpen(true);
						}}
					>
						New Workflow
					</Button>
				</Stack>
			</Stack>

			{/* Workflows Grid */}
			{isLoading ? (
				<Box sx={{ py: 10, textAlign: "center" }}>
					<CircularProgress size={32} />
					<Typography variant="body2" sx={{ mt: 2, color: "text.secondary" }}>
						Loading workflows...
					</Typography>
				</Box>
			) : workflows.length === 0 ? (
				<Paper
					elevation={0}
					sx={{
						p: 6,
						textAlign: "center",
						border: `1px dashed ${theme.palette.divider}`,
						borderRadius: 3,
					}}
				>
					<AccountTree sx={{ fontSize: 48, color: "text.secondary", mb: 1 }} />
					<Typography variant="h6" fontWeight={600}>
						No Workflows Configured
					</Typography>
					<Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
						Create a workflow to automate your API integrations and encryption pipelines.
					</Typography>
					<Button
						variant="contained"
						startIcon={<Add />}
						onClick={() => setCreateOpen(true)}
					>
						Create First Workflow
					</Button>
				</Paper>
			) : (
				<Grid container spacing={2.5}>
					{workflows.map((wf) => (
						<Grid item xs={12} md={6} key={wf.id}>
							<Card
								elevation={0}
								sx={{
									height: "100%",
									display: "flex",
									flexDirection: "column",
									border: `1px solid ${theme.palette.divider}`,
									borderRadius: 2.5,
									transition: "all 0.2s ease-in-out",
									"&:hover": {
										borderColor: "primary.main",
										boxShadow: `0 4px 20px ${alpha(theme.palette.primary.main, 0.08)}`,
									},
								}}
							>
								<CardContent sx={{ p: 2.5, flex: 1, display: "flex", flexDirection: "column" }}>
									<Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1 }}>
										<Box>
											<Typography variant="h6" fontWeight={700}>
												{wf.name}
											</Typography>
											<Typography
												variant="caption"
												sx={{
													fontFamily: "monospace",
													bgcolor: alpha(theme.palette.primary.main, 0.08),
													color: "primary.main",
													px: 0.8,
													py: 0.2,
													borderRadius: 1,
													fontWeight: 600,
												}}
											>
												slug: {wf.slug}
											</Typography>
										</Box>
										<Stack direction="row" spacing={1} alignItems="center">
											<Tooltip title={wf.is_active ? "Click to set INACTIVE" : "Click to set LIVE"}>
												<Chip
													label={wf.is_active ? "● LIVE" : "○ INACTIVE"}
													size="small"
													color={wf.is_active ? "success" : "default"}
													variant={wf.is_active ? "filled" : "outlined"}
													clickable
													onClick={(e) => {
														e.stopPropagation();
														toggleActiveMutation.mutate({ id: wf.id, is_active: !wf.is_active });
													}}
													sx={{
														fontWeight: 700,
														fontSize: "0.72rem",
														cursor: "pointer",
														userSelect: "none",
														transition: "all 0.15s ease",
														"&:hover": {
															opacity: 0.85,
														},
													}}
												/>
											</Tooltip>
											<Tooltip title={wf.is_active ? "Click to Pause (Unlive)" : "Click to Make LIVE (Activate Webhook)"}>
												<Switch
													size="small"
													color="success"
													checked={Boolean(wf.is_active)}
													disabled={toggleActiveMutation.isPending && toggleActiveMutation.variables?.id === wf.id}
													onChange={(e) => {
														e.stopPropagation();
														toggleActiveMutation.mutate({ id: wf.id, is_active: e.target.checked });
													}}
												/>
											</Tooltip>
										</Stack>
									</Stack>

									<Typography
										variant="body2"
										color="text.secondary"
										sx={{
											mt: 1,
											mb: 2,
											flex: 1,
											display: "-webkit-box",
											WebkitLineClamp: 2,
											WebkitBoxOrient: "vertical",
											overflow: "hidden",
										}}
									>
										{wf.description || "No description provided."}
									</Typography>

									<Divider sx={{ my: 1.5 }} />

									{/* Stats & Last Run */}
									<Stack
										direction="row"
										justifyContent="space-between"
										alignItems="center"
										sx={{ mb: 2 }}
									>
										<Chip
											label={`${wf.step_count || 0} Steps`}
											size="small"
											variant="outlined"
											icon={<AccountTree fontSize="inherit" />}
										/>

										{wf.last_run ? (
											<Stack direction="row" alignItems="center" spacing={0.5}>
												{wf.last_run.status === "SUCCESS" ? (
													<CheckCircleOutline fontSize="small" color="success" />
												) : (
													<ErrorOutline fontSize="small" color="error" />
												)}
												<Typography variant="caption" fontWeight={600}>
													{wf.last_run.status} ({wf.last_run.total_time_ms}ms)
												</Typography>
											</Stack>
										) : (
											<Typography variant="caption" color="text.secondary">
												Never run
											</Typography>
										)}
									</Stack>

									{/* Action Buttons */}
									<Stack direction="row" spacing={1} justifyContent="flex-end">
										<Button
											variant="outlined"
											color="primary"
											size="small"
											startIcon={<PlayArrow />}
											onClick={() => handleOpenRun(wf)}
										>
											Test Run
										</Button>
										<Button
											variant="contained"
											size="small"
											endIcon={<TrendingFlat />}
											onClick={() => navigate(`/workflows/${wf.id}`)}
										>
											Open Builder
										</Button>
										<Tooltip title="Delete Workflow">
											<IconButton
												size="small"
												color="error"
												onClick={() => {
													if (window.confirm(`Delete workflow "${wf.name}"?`)) {
														deleteMutation.mutate(wf.id);
													}
												}}
											>
												<DeleteOutline fontSize="small" />
											</IconButton>
										</Tooltip>
									</Stack>
								</CardContent>
							</Card>
						</Grid>
					))}
				</Grid>
			)}

			{/* Modal for Creating Workflow */}
			<Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
				<form
					onSubmit={(e) => {
						e.preventDefault();
						createMutation.mutate(createForm);
					}}
				>
					<DialogTitle>Create New Workflow</DialogTitle>
					<DialogContent dividers>
						<Stack spacing={2.5} sx={{ pt: 1 }}>
							<TextField
								label="Workflow Name"
								required
								fullWidth
								size="small"
								value={createForm.name}
								onChange={(e) => {
									const name = e.target.value;
									const autoSlug = name
										.toLowerCase()
										.replace(/[^a-z0-9]+/g, "-")
										.replace(/^-+|-+$/g, "");
									setCreateForm({
										...createForm,
										name,
										slug: createForm.slug ? createForm.slug : autoSlug,
									});
								}}
								placeholder="e.g. SSPA MIS Complaint Intake"
							/>

							<TextField
								label="Workflow Slug"
								required
								fullWidth
								size="small"
								value={createForm.slug}
								onChange={(e) =>
									setCreateForm({
										...createForm,
										slug: e.target.value.toLowerCase().replace(/[^a-z0-9\-]+/g, "-"),
									})
								}
								helperText="Unique identifier for executing via webhook: /api/workflows/execute-by-slug/{slug}"
							/>

							<TextField
								label="Description"
								fullWidth
								size="small"
								multiline
								rows={3}
								value={createForm.description}
								onChange={(e) =>
									setCreateForm({ ...createForm, description: e.target.value })
								}
								placeholder="Purpose and details of this workflow..."
							/>
						</Stack>
					</DialogContent>
					<DialogActions>
						<Button onClick={() => setCreateOpen(false)}>Cancel</Button>
						<Button type="submit" variant="contained" disabled={createMutation.isPending}>
							{createMutation.isPending ? "Creating..." : "Create Workflow"}
						</Button>
					</DialogActions>
				</form>
			</Dialog>

			{/* Modal for Testing / Executing Workflow */}
			<Dialog open={runOpen} onClose={() => setRunOpen(false)} maxWidth="md" fullWidth>
				<DialogTitle>
					Test Run: {activeWorkflow?.name}
				</DialogTitle>
				<DialogContent dividers>
					<Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
						Provide trigger input JSON to run through this workflow pipeline. Step-by-step results and outputs will appear below.
					</Typography>

					<TextField
						label="Trigger Input JSON"
						fullWidth
						multiline
						rows={8}
						value={triggerPayloadInput}
						onChange={(e) => setTriggerPayloadInput(e.target.value)}
						slotProps={{
							input: {
								sx: { fontFamily: "monospace", fontSize: "0.85rem" },
							},
						}}
					/>

					{runMutation.isPending && (
						<Box sx={{ py: 4, textAlign: "center" }}>
							<CircularProgress size={32} />
							<Typography variant="body2" sx={{ mt: 1, color: "text.secondary" }}>
								Executing pipeline steps in sequence...
							</Typography>
						</Box>
					)}

					{runResult && (
						<Box sx={{ mt: 3 }}>
							<Alert
								severity={runResult.status === "SUCCESS" ? "success" : "error"}
								sx={{ mb: 2 }}
							>
								Status: <b>{runResult.status}</b> | Total Duration: <b>{runResult.total_time_ms} ms</b>
								{runResult.error && (
									<Typography variant="body2" sx={{ mt: 0.5 }}>
										Error: {runResult.error}
									</Typography>
								)}
							</Alert>

							<Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
								Step Results:
							</Typography>
							<Stack spacing={1} sx={{ mb: 2 }}>
								{runResult.step_results?.map((res, i) => (
									<Paper
										key={i}
										elevation={0}
										sx={{
											p: 1.5,
											border: `1px solid ${theme.palette.divider}`,
											borderRadius: 1.5,
											bgcolor: alpha(
												res.status === "SUCCESS"
													? theme.palette.success.main
													: theme.palette.error.main,
												0.04,
											),
										}}
									>
										<Stack direction="row" justifyContent="space-between" alignItems="center">
											<Stack direction="row" spacing={1} alignItems="center">
												{res.status === "SUCCESS" ? (
													<CheckCircleOutline fontSize="small" color="success" />
												) : (
													<ErrorOutline fontSize="small" color="error" />
												)}
												<Typography variant="body2" fontWeight={700} sx={{ fontFamily: "monospace" }}>
													{res.step_key}
												</Typography>
												<Chip label={res.step_type} size="small" variant="outlined" />
											</Stack>
											<Typography variant="caption" color="text.secondary">
												{res.duration_ms} ms
											</Typography>
										</Stack>
										{res.error && (
											<Typography variant="caption" color="error" sx={{ mt: 0.5, display: "block" }}>
												{res.error}
											</Typography>
										)}
									</Paper>
								))}
							</Stack>

							<Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
								Final Output:
							</Typography>
							<Paper
								elevation={0}
								sx={{
									p: 2,
									bgcolor: alpha(theme.palette.background.default, 0.7),
									border: `1px solid ${theme.palette.divider}`,
									borderRadius: 1.5,
									maxHeight: 250,
									overflowY: "auto",
								}}
							>
								<pre style={{ margin: 0, fontFamily: "monospace", fontSize: "0.8rem" }}>
									{JSON.stringify(runResult.final_output, null, 2)}
								</pre>
							</Paper>
						</Box>
					)}
				</DialogContent>
				<DialogActions>
					<Button onClick={() => setRunOpen(false)}>Close</Button>
					<Button
						variant="contained"
						startIcon={<PlayArrow />}
						onClick={handleExecuteRun}
						disabled={runMutation.isPending}
					>
						Execute Pipeline
					</Button>
				</DialogActions>
			</Dialog>
		</Box>
	);
}
