import {
	AccountTree,
	Add,
	ArrowBack,
	ArrowDownward,
	ArrowUpward,
	CheckCircleOutline,
	Code as CodeIcon,
	ContentCopy,
	ContentPaste,
	DeleteOutline,
	ErrorOutline,
	ExpandMore,
	Http,
	Key,
	Lock,
	LockOpen,
	PlayArrow,
	Refresh,
	Save,
	Send,
	Terminal,
	Visibility,
} from "@mui/icons-material";
import {
	Accordion,
	AccordionDetails,
	AccordionSummary,
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
	Drawer,
	FormControl,
	Grid,
	IconButton,
	InputLabel,
	MenuItem,
	Paper,
	Select,
	Stack,
	Switch,
	Tab,
	Tabs,
	TextField,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useSnackbar } from "../context/SnackbarContext";
import workflowService from "../services/workflowService";

const NODE_TYPES = [
	{ value: "start_webhook", label: "Start Webhook", icon: <Send fontSize="small" />, color: "#ed6c02" },
	{ value: "code", label: "Code Node (Python)", icon: <CodeIcon fontSize="small" />, color: "#9c27b0" },
	{ value: "http_request", label: "Hit API (cURL)", icon: <Http fontSize="small" />, color: "#0288d1" },
	{ value: "aes_encrypt", label: "AES-256-GCM Encrypt", icon: <Lock fontSize="small" />, color: "#2e7d32" },
	{ value: "aes_decrypt", label: "AES-256-GCM Decrypt", icon: <LockOpen fontSize="small" />, color: "#00897b" },
	{ value: "transform", label: "Data Transform", icon: <AccountTree fontSize="small" />, color: "#f57c00" },
	{ value: "output", label: "Workflow Output", icon: <CheckCircleOutline fontSize="small" />, color: "#3f51b5" },
];

export default function WorkflowBuilderPage() {
	const theme = useTheme();
	const navigate = useNavigate();
	const { id } = useParams();
	const queryClient = useQueryClient();
	const { showSuccess, showError } = useSnackbar();

	const [activeTab, setActiveTab] = useState(0);
	const [selectedStep, setSelectedStep] = useState(null);
	const [stepConfigForm, setStepConfigForm] = useState(null);
	const [testResult, setTestResult] = useState(null);

	// cURL Import Modal
	const [curlModalOpen, setCurlModalOpen] = useState(false);
	const [curlInput, setCurlInput] = useState("");

	// Full Run Dialog
	const [runOpen, setRunOpen] = useState(false);
	const [runPayload, setRunPayload] = useState("{}");
	const [runResult, setRunResult] = useState(null);

	// Add Step Dialog
	const [addStepOpen, setAddStepOpen] = useState(false);
	const [newStepType, setNewStepType] = useState("start_webhook");
	const [newStepKey, setNewStepKey] = useState("");

	const { data: workflow, isLoading, isFetching, refetch } = useQuery({
		queryKey: ["workflow", id],
		queryFn: () => workflowService.getWorkflow(id),
	});

	const { data: runs = [] } = useQuery({
		queryKey: ["workflow-runs", id],
		queryFn: () => workflowService.getWorkflowRuns(id),
		enabled: activeTab === 1,
	});

	const steps = useMemo(() => {
		if (!workflow?.steps) return [];
		return [...workflow.steps].sort((a, b) => a.step_order - b.step_order);
	}, [workflow]);

	useEffect(() => {
		if (steps.length > 0 && !selectedStep) {
			handleSelectStep(steps[0]);
		}
	}, [steps]);

	const handleSelectStep = (step) => {
		setSelectedStep(step);
		setTestResult(null);

		// Normalize type if old name was used
		let normalizedType = step.step_type;
		if (normalizedType === "trigger") normalizedType = "start_webhook";
		if (normalizedType === "curl") normalizedType = "http_request";

		setStepConfigForm({
			step_key: step.step_key,
			step_type: normalizedType,
			step_order: step.step_order,
			is_active: step.is_active,
			configJson: JSON.stringify(step.config || {}, null, 2),
			code: step.config?.code || "",
		});
	};

	const updateStepMutation = useMutation({
		mutationFn: ({ stepId, data }) => workflowService.updateStep(id, stepId, data),
		onSuccess: () => {
			showSuccess("Step configuration saved");
			queryClient.invalidateQueries({ queryKey: ["workflow", id] });
		},
		onError: (err) => {
			showError(err.response?.data?.detail || err.message || "Failed to update step");
		},
	});

	const addStepMutation = useMutation({
		mutationFn: (data) => workflowService.addStep(id, data),
		onSuccess: () => {
			showSuccess("Step added to pipeline");
			queryClient.invalidateQueries({ queryKey: ["workflow", id] });
			setAddStepOpen(false);
		},
		onError: (err) => {
			showError(err.response?.data?.detail || err.message || "Failed to add step");
		},
	});

	const deleteStepMutation = useMutation({
		mutationFn: (stepId) => workflowService.deleteStep(id, stepId),
		onSuccess: () => {
			showSuccess("Step removed");
			setSelectedStep(null);
			queryClient.invalidateQueries({ queryKey: ["workflow", id] });
		},
		onError: (err) => {
			showError(err.response?.data?.detail || err.message || "Failed to delete step");
		},
	});

	const reorderMutation = useMutation({
		mutationFn: (newSteps) => workflowService.reorderSteps(id, newSteps),
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["workflow", id] });
		},
	});

	const testStepMutation = useMutation({
		mutationFn: ({ stepId, context, config, stepType }) =>
			workflowService.testStep(id, stepId, context, config, stepType),
		onSuccess: (data) => {
			setTestResult(data);
			if (data?.status === "SUCCESS") {
				showSuccess(`Step completed in ${data.duration_ms}ms`);
			} else {
				showError(`Step failed: ${data?.error}`);
			}
		},
		onError: (err) => {
			showError(err.response?.data?.detail || err.message || "Test failed");
		},
	});

	const runWorkflowMutation = useMutation({
		mutationFn: (payload) => workflowService.runWorkflow(id, payload),
		onSuccess: (data) => {
			setRunResult(data);
			queryClient.invalidateQueries({ queryKey: ["workflow", id] });
			queryClient.invalidateQueries({ queryKey: ["workflow-runs", id] });
			if (data?.status === "SUCCESS") {
				showSuccess(`Workflow completed successfully in ${data.total_time_ms}ms`);
			} else {
				showError(`Workflow execution failed`);
			}
		},
		onError: (err) => {
			showError(err.response?.data?.detail?.message || err.message || "Run failed");
		},
	});

	const toggleActiveMutation = useMutation({
		mutationFn: (newActive) => workflowService.updateWorkflow(id, { is_active: newActive }),
		onSuccess: (_, newActive) => {
			showSuccess(
				newActive
					? "Workflow is now LIVE! Webhook listener is actively listening."
					: "Workflow paused (Unlive / Inactive). Webhook listener paused."
			);
			queryClient.invalidateQueries({ queryKey: ["workflow", id] });
			queryClient.invalidateQueries({ queryKey: ["workflows"] });
		},
		onError: (err) => {
			showError(err.response?.data?.detail?.message || err.response?.data?.detail || err.message || "Failed to update workflow status");
		},
	});

	const handleSaveStep = () => {
		if (!selectedStep || !stepConfigForm) return;
		let finalConfig = {};

		if (stepConfigForm.step_type === "code") {
			try {
				finalConfig = JSON.parse(stepConfigForm.configJson || "{}");
			} catch {
				finalConfig = {};
			}
			finalConfig.code = stepConfigForm.code;
		} else {
			try {
				finalConfig = JSON.parse(stepConfigForm.configJson);
			} catch (e) {
				showError("Invalid JSON in configuration");
				return;
			}
		}

		updateStepMutation.mutate({
			stepId: selectedStep.id,
			data: {
				step_key: stepConfigForm.step_key,
				step_type: stepConfigForm.step_type,
				config: finalConfig,
				is_active: stepConfigForm.is_active,
			},
		});
	};

	const handleMoveStep = (index, direction) => {
		const targetIndex = index + direction;
		if (targetIndex < 0 || targetIndex >= steps.length) return;

		const reordered = [...steps];
		const temp = reordered[index];
		reordered[index] = reordered[targetIndex];
		reordered[targetIndex] = temp;

		const payload = reordered.map((s, idx) => ({
			step_id: s.id,
			step_order: idx + 1,
		}));

		reorderMutation.mutate(payload);
	};

	const handleApplyCurl = async () => {
		if (!curlInput.trim()) return;
		try {
			const parsed = await workflowService.parseCurl(curlInput);
			if (parsed) {
				const current = JSON.parse(stepConfigForm.configJson || "{}");
				const merged = {
					...current,
					method: parsed.method,
					url: parsed.url,
					headers: parsed.headers,
					body: parsed.body,
				};
				setStepConfigForm({
					...stepConfigForm,
					configJson: JSON.stringify(merged, null, 2),
				});
				showSuccess("cURL command parsed and applied to Hit API node");
				setCurlModalOpen(false);
				setCurlInput("");
			}
		} catch (err) {
			showError("Failed to parse cURL: " + (err.response?.data?.detail || err.message));
		}
	};

	const handleTestSingleStep = () => {
		if (!selectedStep) return;
		let triggerData = {};
		const triggerStep = steps.find((s) => s.step_type === "start_webhook" || s.step_type === "trigger");
		if (triggerStep?.config?.default_payload) {
			triggerData = triggerStep.config.default_payload;
		}

		let currentConfig = null;
		if (stepConfigForm) {
			if (stepConfigForm.step_type === "code") {
				try {
					currentConfig = JSON.parse(stepConfigForm.configJson || "{}");
				} catch {
					currentConfig = {};
				}
				currentConfig.code = stepConfigForm.code;
			} else {
				try {
					currentConfig = JSON.parse(stepConfigForm.configJson);
				} catch {
					currentConfig = null;
				}
			}
		}

		testStepMutation.mutate({
			stepId: selectedStep.id,
			context: {
				trigger: triggerData,
				nodes: {
					login: {
						data: { access_token: "test-token-xyz" },
					},
					prepare_payload: {
						output: {
							source_ticket_id: "IMIS-TICKET-2026-00123",
							benef_cnic: "42201-1234567-1",
							category: "Payments",
							complaint_type: "benef",
						},
					},
				},
			},
			config: currentConfig,
			stepType: stepConfigForm?.step_type,
		});
	};

	const getNodeMeta = (type) => {
		let t = type;
		if (t === "trigger") t = "start_webhook";
		if (t === "curl") t = "http_request";
		return NODE_TYPES.find((n) => n.value === t) || NODE_TYPES[0];
	};

	const webhookUrl = `${window.location.protocol}//${window.location.host}/api/workflows/webhook/${workflow?.slug || ""}`;

	if (isLoading) {
		return (
			<Box sx={{ py: 12, textAlign: "center" }}>
				<CircularProgress size={32} />
				<Typography variant="body2" sx={{ mt: 2, color: "text.secondary" }}>
					Loading workflow builder...
				</Typography>
			</Box>
		);
	}

	if (!workflow) {
		return (
			<Alert severity="error">
				Workflow not found. <Button onClick={() => navigate("/workflows")}>Back</Button>
			</Alert>
		);
	}

	return (
		<Box sx={{ pb: 6 }}>
			{/* Top Bar */}
			<Stack
				direction={{ xs: "column", sm: "row" }}
				justifyContent="space-between"
				alignItems={{ xs: "flex-start", sm: "center" }}
				gap={2}
				sx={{ mb: 3 }}
			>
				<Stack direction="row" spacing={1.5} alignItems="center">
					<IconButton onClick={() => navigate("/workflows")}>
						<ArrowBack />
					</IconButton>
					<Box>
						<Stack direction="row" spacing={1} alignItems="center">
							<Typography variant="h5" fontWeight={700}>
								{workflow.name}
							</Typography>
							<Chip label={`slug: ${workflow.slug}`} size="small" variant="outlined" />
						</Stack>
						<Typography variant="body2" color="text.secondary">
							{workflow.description || "Interactive pipeline with Start Webhook, Code Node, and Hit API (cURL)."}
						</Typography>
					</Box>
				</Stack>

				<Stack direction="row" spacing={1.5} alignItems="center">
					{/* Live / Unlive Mode Switch */}
					<Paper
						variant="outlined"
						sx={{
							px: 1.5,
							py: 0.5,
							display: "flex",
							alignItems: "center",
							gap: 1.2,
							borderColor: workflow.is_active ? "success.main" : "divider",
							bgcolor: workflow.is_active
								? alpha(theme.palette.success.main, 0.08)
								: alpha(theme.palette.action.disabledBackground, 0.04),
							borderRadius: 2,
						}}
					>
						<Stack direction="row" alignItems="center" spacing={0.8}>
							<Box
								sx={{
									width: 8,
									height: 8,
									borderRadius: "50%",
									bgcolor: workflow.is_active ? "success.main" : "text.disabled",
									boxShadow: workflow.is_active ? "0 0 6px #2e7d32" : "none",
								}}
							/>
							<Typography
								variant="caption"
								fontWeight={700}
								color={workflow.is_active ? "success.main" : "text.secondary"}
								sx={{ letterSpacing: 0.5 }}
							>
								{workflow.is_active ? "LIVE LISTENER" : "INACTIVE"}
							</Typography>
						</Stack>
						<Tooltip
							title={
								workflow.is_active
									? "Click to Pause / Unlive (reject inbound webhook requests)"
									: "Click to Make LIVE (start listening for inbound webhook requests)"
							}
						>
							<Switch
								size="small"
								color="success"
								checked={Boolean(workflow.is_active)}
								disabled={toggleActiveMutation.isPending}
								onChange={(e) => toggleActiveMutation.mutate(e.target.checked)}
							/>
						</Tooltip>
					</Paper>

					<Button
						variant="outlined"
						size="small"
						startIcon={isFetching ? <CircularProgress size={16} /> : <Refresh />}
						onClick={() => refetch()}
					>
						Refresh
					</Button>
					<Button
						variant="outlined"
						color="primary"
						size="small"
						startIcon={<Add />}
						onClick={() => {
							setNewStepKey(`step_${steps.length + 1}`);
							setAddStepOpen(true);
						}}
					>
						Add Node
					</Button>
					<Button
						variant="contained"
						color="primary"
						size="small"
						startIcon={<PlayArrow />}
						onClick={() => {
							const triggerStep = steps.find((s) => s.step_type === "start_webhook" || s.step_type === "trigger");
							const defaultJson = triggerStep?.config?.default_payload
								? JSON.stringify(triggerStep.config.default_payload, null, 2)
								: "{}";
							setRunPayload(defaultJson);
							setRunResult(null);
							setRunOpen(true);
						}}
					>
						Run Full Workflow
					</Button>
				</Stack>
			</Stack>

			{/* Tabs */}
			<Tabs
				value={activeTab}
				onChange={(_, v) => setActiveTab(v)}
				sx={{ mb: 3, borderBottom: `1px solid ${theme.palette.divider}` }}
			>
				<Tab label="Visual Step Pipeline" />
				<Tab label="Run History & Logs" />
			</Tabs>

			{activeTab === 0 ? (
				<Grid container spacing={3}>
					{/* Left Column: Visual Steps Pipeline */}
					<Grid item xs={12} md={5} lg={4}>
						<Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5, color: "text.secondary" }}>
							PIPELINE SEQUENCE ({steps.length} NODES)
						</Typography>

						<Stack spacing={1.5}>
							{steps.map((step, idx) => {
								const meta = getNodeMeta(step.step_type);
								const isSelected = selectedStep?.id === step.id;

								return (
									<Card
										key={step.id}
										elevation={0}
										onClick={() => handleSelectStep(step)}
										sx={{
											cursor: "pointer",
											border: `1.5px solid ${
												isSelected ? theme.palette.primary.main : theme.palette.divider
											}`,
											borderRadius: 2,
											bgcolor: isSelected
												? alpha(theme.palette.primary.main, 0.04)
												: theme.palette.background.paper,
											transition: "all 0.15s ease",
											"&:hover": {
												borderColor: theme.palette.primary.main,
											},
										}}
									>
										<CardContent sx={{ p: 1.5, "&:last-child": { pb: 1.5 } }}>
											<Stack direction="row" justifyContent="space-between" alignItems="center">
												<Stack direction="row" spacing={1.5} alignItems="center">
													<Box
														sx={{
															width: 34,
															height: 34,
															borderRadius: 1.5,
															display: "flex",
															alignItems: "center",
															justifyContent: "center",
															bgcolor: alpha(meta.color, 0.12),
															color: meta.color,
														}}
													>
														{meta.icon}
													</Box>
													<Box>
														<Stack direction="row" spacing={0.8} alignItems="center">
															<Typography variant="caption" fontWeight={700} color="text.secondary">
																#{step.step_order}
															</Typography>
															<Typography variant="body2" fontWeight={700} sx={{ fontFamily: "monospace" }}>
																{step.step_key}
															</Typography>
														</Stack>
														<Typography variant="caption" sx={{ color: meta.color, fontWeight: 600 }}>
															{meta.label}
														</Typography>
													</Box>
												</Stack>

												<Stack direction="row" spacing={0.5} onClick={(e) => e.stopPropagation()}>
													<IconButton
														size="small"
														disabled={idx === 0}
														onClick={() => handleMoveStep(idx, -1)}
													>
														<ArrowUpward fontSize="inherit" />
													</IconButton>
													<IconButton
														size="small"
														disabled={idx === steps.length - 1}
														onClick={() => handleMoveStep(idx, 1)}
													>
														<ArrowDownward fontSize="inherit" />
													</IconButton>
												</Stack>
											</Stack>
										</CardContent>
									</Card>
								);
							})}

							<Button
								variant="dashed"
								fullWidth
								startIcon={<Add />}
								onClick={() => {
									setNewStepKey(`step_${steps.length + 1}`);
									setAddStepOpen(true);
								}}
								sx={{
									py: 1.5,
									border: `1px dashed ${theme.palette.divider}`,
									borderRadius: 2,
									textTransform: "none",
								}}
							>
								Add Next Node
							</Button>
						</Stack>
					</Grid>

					{/* Right Column: Node Configuration Panel */}
					<Grid item xs={12} md={7} lg={8}>
						{selectedStep && stepConfigForm ? (
							<Paper
								elevation={0}
								sx={{
									p: 3,
									border: `1px solid ${theme.palette.divider}`,
									borderRadius: 2.5,
								}}
							>
								{/* Node Header */}
								<Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
									<Box>
										<Stack direction="row" spacing={1} alignItems="center">
											<Typography variant="h6" fontWeight={700}>
												{getNodeMeta(stepConfigForm.step_type).label}: {stepConfigForm.step_key}
											</Typography>
											<Chip
												label={getNodeMeta(stepConfigForm.step_type).label}
												size="small"
												sx={{
													fontWeight: 600,
													bgcolor: alpha(getNodeMeta(stepConfigForm.step_type).color, 0.12),
													color: getNodeMeta(stepConfigForm.step_type).color,
												}}
											/>
										</Stack>
										<Typography variant="caption" color="text.secondary">
											Reference output in downstream nodes via <code>{`{{nodes.${stepConfigForm.step_key}.output}}`}</code>
										</Typography>
									</Box>

									<Stack direction="row" spacing={1}>
										{stepConfigForm.step_type === "http_request" && (
											<Button
												variant="outlined"
												color="secondary"
												size="small"
												startIcon={<ContentPaste />}
												onClick={() => setCurlModalOpen(true)}
											>
												Import cURL
											</Button>
										)}
										<Button
											variant="outlined"
											size="small"
											startIcon={<PlayArrow />}
											onClick={handleTestSingleStep}
											disabled={testStepMutation.isPending}
										>
											{testStepMutation.isPending ? "Testing..." : "Test Node"}
										</Button>
										<Button
											variant="contained"
											size="small"
											startIcon={<Save />}
											onClick={handleSaveStep}
											disabled={updateStepMutation.isPending}
										>
											{updateStepMutation.isPending ? "Saving..." : "Save Node"}
										</Button>
										<Tooltip title="Delete Node">
											<IconButton
												size="small"
												color="error"
												onClick={() => {
													if (window.confirm(`Delete step "${selectedStep.step_key}"?`)) {
														deleteStepMutation.mutate(selectedStep.id);
													}
												}}
											>
												<DeleteOutline fontSize="small" />
											</IconButton>
										</Tooltip>
									</Stack>
								</Stack>

								<Divider sx={{ mb: 2.5 }} />

								{/* Node Controls */}
								<Stack spacing={2.5}>
									<Grid container spacing={2}>
										<Grid item xs={12} sm={6}>
											<TextField
												label="Node Identifier (Key)"
												size="small"
												fullWidth
												value={stepConfigForm.step_key}
												onChange={(e) =>
													setStepConfigForm({
														...stepConfigForm,
														step_key: e.target.value.toLowerCase().replace(/[^a-z0-9_]+/g, "_"),
													})
												}
												helperText="Access output via {{nodes.<key>.output}}"
											/>
										</Grid>
										<Grid item xs={12} sm={6}>
											<FormControl fullWidth size="small">
												<InputLabel>Node Type</InputLabel>
												<Select
													value={stepConfigForm.step_type}
													label="Node Type"
													onChange={(e) =>
														setStepConfigForm({
															...stepConfigForm,
															step_type: e.target.value,
														})
													}
												>
													{NODE_TYPES.map((nt) => (
														<MenuItem key={nt.value} value={nt.value}>
															<Stack direction="row" spacing={1} alignItems="center">
																{nt.icon}
																<span>{nt.label}</span>
															</Stack>
														</MenuItem>
													))}
												</Select>
											</FormControl>
										</Grid>
									</Grid>

									{/* 1. START WEBHOOK NODE SPECIFICS */}
									{(stepConfigForm.step_type === "start_webhook" || stepConfigForm.step_type === "trigger") && (
										<Box>
											{workflow.is_active ? (
												<Alert severity="success" sx={{ mb: 2, fontSize: "0.85rem", alignItems: "center" }}>
													<b>🟢 Listener Active:</b> This workflow is <b>LIVE</b> and actively listening for incoming HTTP POST requests at the URL below. Incoming requests will immediately trigger this pipeline.
												</Alert>
											) : (
												<Alert
													severity="warning"
													sx={{ mb: 2, fontSize: "0.85rem", alignItems: "center" }}
													action={
														<Button
															color="inherit"
															size="small"
															variant="outlined"
															onClick={() => toggleActiveMutation.mutate(true)}
														>
															Make Live
														</Button>
													}
												>
													<b>⏸️ Listener Paused:</b> Workflow is currently <b>INACTIVE (Unlive)</b>. Incoming requests to this URL will be rejected with HTTP 403. Flip the LIVE switch above or click Make Live to activate.
												</Alert>
											)}
											<Paper
												elevation={0}
												sx={{
													p: 1.5,
													bgcolor: alpha(theme.palette.primary.main, 0.05),
													border: `1px solid ${theme.palette.divider}`,
													borderRadius: 1.5,
													display: "flex",
													justifyContent: "space-between",
													alignItems: "center",
													mb: 2,
												}}
											>
												<Typography
													variant="body2"
													sx={{ fontFamily: "monospace", fontWeight: 600, color: "primary.main" }}
												>
													POST {webhookUrl}
												</Typography>
												<Tooltip title="Copy Webhook URL">
													<IconButton
														size="small"
														onClick={() => {
															navigator.clipboard.writeText(webhookUrl);
															showSuccess("Copied Webhook URL!");
														}}
													>
														<ContentCopy fontSize="small" />
													</IconButton>
												</Tooltip>
											</Paper>

											<Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
												DEFAULT SAMPLE PAYLOAD (JSON)
											</Typography>
											<TextField
												fullWidth
												multiline
												rows={9}
												value={stepConfigForm.configJson}
												onChange={(e) =>
													setStepConfigForm({ ...stepConfigForm, configJson: e.target.value })
												}
												slotProps={{
													input: {
														sx: { fontFamily: "monospace", fontSize: "0.82rem" },
													},
												}}
											/>
										</Box>
									)}

									{/* 2. CODE NODE SPECIFICS */}
									{stepConfigForm.step_type === "code" && (
										<Box>
											<Alert severity="info" sx={{ mb: 1.5, fontSize: "0.85rem" }}>
												<b>Python Code Node:</b> Run custom transformations or encryption. Variables available: <code>trigger</code>, <code>nodes</code>, <code>env</code>, and <code>crypto.encrypt_sspa_payload</code>. Use <code>return ...</code> to return step data.
											</Alert>

											{/* Code Snippet Helper Chips */}
											<Stack direction="row" spacing={0.8} sx={{ mb: 1.5, flexWrap: "wrap", gap: 0.8 }}>
												<Chip
													label="Insert AES Encryption snippet"
													size="small"
													onClick={() => {
														const snippet = `# Prepare and Encrypt with SSPA AES-256-GCM\npayload = {\n    "source_ticket_id": trigger.get("source_ticket_id"),\n    "benef_cnic": trigger.get("benef_cnic"),\n    "category": trigger.get("category", "Payments"),\n    "description": trigger.get("description"),\n}\nencrypted = crypto.encrypt_sspa_payload(payload, env["MIS_AES_KEY"])\nreturn encrypted\n`;
														setStepConfigForm({
															...stepConfigForm,
															code: snippet,
														});
													}}
													variant="outlined"
													icon={<Lock fontSize="small" />}
												/>
												<Chip
													label="Insert Token Extraction snippet"
													size="small"
													onClick={() => {
														const snippet = `token = nodes.get("login", {}).get("data", {}).get("access_token")\nreturn {"access_token": token}\n`;
														setStepConfigForm({
															...stepConfigForm,
															code: snippet,
														});
													}}
													variant="outlined"
													icon={<Key fontSize="small" />}
												/>
											</Stack>

											<Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
												PYTHON CODE
											</Typography>
											<TextField
												fullWidth
												multiline
												rows={14}
												value={stepConfigForm.code}
												onChange={(e) =>
													setStepConfigForm({ ...stepConfigForm, code: e.target.value })
												}
												placeholder="# Write your Python logic here\n# Available objects: trigger, nodes, env, crypto\nreturn { ... }"
												slotProps={{
													input: {
														sx: {
															fontFamily: "monospace",
															fontSize: "0.85rem",
															bgcolor: alpha(theme.palette.background.default, 0.7),
														},
													},
												}}
											/>
										</Box>
									)}

									{/* 3. HIT API (cURL) NODE SPECIFICS */}
									{(stepConfigForm.step_type === "http_request" || stepConfigForm.step_type === "curl") && (
										<Box>
											<Alert severity="info" sx={{ mb: 1.5, fontSize: "0.85rem" }}>
												<b>Hit API Node:</b> Click <b>Import cURL</b> to paste an existing cURL request, or edit the JSON configuration below with dynamic references like <code>{`{{env.MIS_BASE_URL}}`}</code> and <code>{`{{nodes.login.data.access_token}}`}</code>.
											</Alert>

											<Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
												HTTP REQUEST CONFIGURATION (JSON)
											</Typography>
											<TextField
												fullWidth
												multiline
												rows={12}
												value={stepConfigForm.configJson}
												onChange={(e) =>
													setStepConfigForm({ ...stepConfigForm, configJson: e.target.value })
												}
												slotProps={{
													input: {
														sx: { fontFamily: "monospace", fontSize: "0.82rem" },
													},
												}}
											/>
										</Box>
									)}

									{/* 4. OTHER NODES (AES Encrypt, Decrypt, Transform, Output) */}
									{!["start_webhook", "trigger", "code", "http_request", "curl"].includes(stepConfigForm.step_type) && (
										<Box>
											<Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
												NODE CONFIGURATION (JSON)
											</Typography>
											<TextField
												fullWidth
												multiline
												rows={12}
												value={stepConfigForm.configJson}
												onChange={(e) =>
													setStepConfigForm({ ...stepConfigForm, configJson: e.target.value })
												}
												slotProps={{
													input: {
														sx: { fontFamily: "monospace", fontSize: "0.82rem" },
													},
												}}
											/>
										</Box>
									)}
								</Stack>

								{/* Step Test Result Preview */}
								{testResult && (
									<Box sx={{ mt: 3 }}>
										<Divider sx={{ mb: 2 }} />
										<Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
											<Typography variant="subtitle2" fontWeight={700}>
												Node Test Result ({testResult.status} - {testResult.duration_ms}ms)
											</Typography>
											<Stack direction="row" spacing={1} alignItems="center">
												{testResult.http_log?.request?.curl_command && (
													<Button
														size="small"
														variant="outlined"
														startIcon={<ContentCopy fontSize="small" />}
														onClick={() => {
															navigator.clipboard.writeText(testResult.http_log.request.curl_command);
															showSuccess("cURL command copied to clipboard!");
														}}
														sx={{ fontSize: "0.72rem", py: 0.2 }}
													>
														Copy cURL
													</Button>
												)}
												<Chip
													label={testResult.status}
													color={testResult.status === "SUCCESS" ? "success" : "error"}
													size="small"
												/>
											</Stack>
										</Stack>
										{testResult.error && (
											<Alert severity="error" sx={{ mb: 1 }}>
												{testResult.error}
											</Alert>
										)}
										<Paper
											elevation={0}
											sx={{
												p: 1.5,
												bgcolor: alpha(theme.palette.background.default, 0.7),
												border: `1px solid ${theme.palette.divider}`,
												borderRadius: 1.5,
												maxHeight: 220,
												overflowY: "auto",
											}}
										>
											<pre style={{ margin: 0, fontFamily: "monospace", fontSize: "0.78rem" }}>
												{JSON.stringify(testResult.output ?? testResult.http_log?.response?.body, null, 2)}
											</pre>
										</Paper>
									</Box>
								)}
							</Paper>
						) : (
							<Paper
								elevation={0}
								sx={{
									p: 6,
									textAlign: "center",
									border: `1px dashed ${theme.palette.divider}`,
									borderRadius: 2.5,
								}}
							>
								<Typography variant="body1" color="text.secondary">
									Select a node from the pipeline on the left to edit its configuration or test it.
								</Typography>
							</Paper>
						)}
					</Grid>
				</Grid>
			) : (
				/* Tab 1: Run History */
				<Paper
					elevation={0}
					sx={{ border: `1px solid ${theme.palette.divider}`, borderRadius: 2, p: 2 }}
				>
					<Typography variant="h6" fontWeight={700} sx={{ mb: 2 }}>
						Execution History & Trace Logs
					</Typography>
					{runs.length === 0 ? (
						<Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
							No runs recorded yet. Click "Run Full Workflow" to execute this pipeline.
						</Typography>
					) : (
						<Stack spacing={2}>
							{runs.map((r) => (
								<Paper
									key={r.id}
									elevation={0}
									sx={{
										p: 2.5,
										border: `1px solid ${theme.palette.divider}`,
										borderRadius: 2,
										bgcolor: alpha(
											r.status === "SUCCESS"
												? theme.palette.success.main
												: theme.palette.error.main,
											0.02,
										),
									}}
								>
									{/* Run Summary Header */}
									<Stack
										direction={{ xs: "column", sm: "row" }}
										justifyContent="space-between"
										alignItems={{ xs: "flex-start", sm: "center" }}
										gap={1}
										sx={{ mb: 2 }}
									>
										<Stack direction="row" spacing={1.5} alignItems="center">
											<Chip
												label={r.status}
												color={r.status === "SUCCESS" ? "success" : "error"}
												size="small"
												sx={{ fontWeight: 800, fontSize: "0.75rem" }}
											/>
											<Typography
												variant="caption"
												sx={{
													fontFamily: "monospace",
													bgcolor: alpha(theme.palette.text.primary, 0.06),
													px: 1,
													py: 0.3,
													borderRadius: 1,
												}}
											>
												run: {r.id ? `${r.id.slice(0, 8)}...` : ""}
											</Typography>
											<Typography variant="caption" color="text.secondary">
												{new Date(r.ran_at).toLocaleString()}
											</Typography>
										</Stack>

										<Chip
											label={`${r.total_time_ms || 0} ms total`}
											size="small"
											variant="outlined"
											sx={{ fontWeight: 600 }}
										/>
									</Stack>

									{r.error_message && (
										<Alert severity="error" sx={{ mb: 2, py: 0.5, fontSize: "0.85rem" }}>
											{r.error_message}
										</Alert>
									)}

									{/* Step-by-Step Execution Traces */}
									{r.step_results && r.step_results.length > 0 && (
										<Box sx={{ mb: 2 }}>
											<Typography
												variant="caption"
												fontWeight={700}
												color="text.secondary"
												sx={{ display: "block", mb: 1, letterSpacing: 0.5 }}
											>
												PIPELINE STEP EXECUTION TRACE ({r.step_results.length} NODES)
											</Typography>
											<Stack spacing={1}>
												{r.step_results.map((st, sIdx) => {
													const hasHttpLog = Boolean(st.http_log);
													const httpLog = st.http_log;
													return (
														<Accordion
															key={sIdx}
															elevation={0}
															disableGutters
															sx={{
																border: `1px solid ${theme.palette.divider}`,
																borderRadius: 1.5,
																"&:before": { display: "none" },
																overflow: "hidden",
															}}
														>
															<AccordionSummary
																expandIcon={<ExpandMore />}
																sx={{
																	bgcolor: alpha(theme.palette.background.default, 0.6),
																	py: 0.5,
																	minHeight: 48,
																}}
															>
																<Stack
																	direction="row"
																	spacing={1.5}
																	alignItems="center"
																	sx={{ width: "100%", pr: 2, flexWrap: "wrap", gap: 1 }}
																>
																	<Typography
																		variant="caption"
																		fontWeight={700}
																		sx={{ fontFamily: "monospace" }}
																	>
																		#{sIdx + 1} {st.step_key}
																	</Typography>
																	<Chip
																		label={st.step_type}
																		size="small"
																		variant="outlined"
																		sx={{ fontSize: "0.7rem", height: 20 }}
																	/>
																	<Chip
																		label={st.status}
																		size="small"
																		color={st.status === "SUCCESS" ? "success" : "error"}
																		sx={{ fontSize: "0.7rem", height: 20, fontWeight: 700 }}
																	/>
																	{hasHttpLog && (
																		<>
																			<Chip
																				label={httpLog.request?.method || "HTTP"}
																				size="small"
																				color="primary"
																				sx={{ fontSize: "0.7rem", height: 20, fontWeight: 700 }}
																			/>
																			{httpLog.response?.status_code && (
																				<Chip
																					label={`HTTP ${httpLog.response.status_code}`}
																					size="small"
																					color={
																						httpLog.response.status_code < 300
																							? "success"
																							: httpLog.response.status_code < 500
																							? "warning"
																							: "error"
																					}
																					sx={{ fontSize: "0.7rem", height: 20, fontWeight: 700 }}
																				/>
																			)}
																			<Typography
																				variant="caption"
																				sx={{
																					fontFamily: "monospace",
																					color: "text.secondary",
																					maxWidth: 320,
																					overflow: "hidden",
																					textOverflow: "ellipsis",
																					whiteSpace: "nowrap",
																				}}
																			>
																				{httpLog.request?.url}
																			</Typography>
																		</>
																	)}
																	<Box sx={{ flexGrow: 1 }} />
																	<Typography variant="caption" color="text.secondary">
																		{st.duration_ms} ms
																	</Typography>
																</Stack>
															</AccordionSummary>
															<AccordionDetails sx={{ p: 2, bgcolor: theme.palette.background.paper }}>
																{hasHttpLog ? (
																	<Stack spacing={2}>
																		{/* cURL bar with Copy button */}
																		<Paper
																			elevation={0}
																			sx={{
																				p: 1.5,
																				bgcolor: alpha(theme.palette.text.primary, 0.04),
																				border: `1px solid ${theme.palette.divider}`,
																				borderRadius: 1.5,
																			}}
																		>
																			<Stack
																				direction="row"
																				justifyContent="space-between"
																				alignItems="center"
																				sx={{ mb: 1 }}
																			>
																				<Typography
																					variant="caption"
																					fontWeight={700}
																					color="primary.main"
																				>
																					REPRODUCIBLE cURL COMMAND
																				</Typography>
																				<Button
																					size="small"
																					variant="outlined"
																					startIcon={<ContentCopy fontSize="small" />}
																					onClick={() => {
																						navigator.clipboard.writeText(
																							httpLog.request?.curl_command || "",
																						);
																						showSuccess("cURL command copied to clipboard!");
																					}}
																					sx={{ fontSize: "0.72rem", py: 0.2 }}
																				>
																					Copy cURL
																				</Button>
																			</Stack>
																			<pre
																				style={{
																					margin: 0,
																					fontFamily: "monospace",
																					fontSize: "0.75rem",
																					whiteSpace: "pre-wrap",
																					wordBreak: "break-all",
																					maxHeight: 120,
																					overflowY: "auto",
																				}}
																			>
																				{httpLog.request?.curl_command}
																			</pre>
																		</Paper>

																		<Grid container spacing={2}>
																			{/* Outbound Request Details */}
																			<Grid item xs={12} md={6}>
																				<Typography
																					variant="caption"
																					fontWeight={700}
																					color="text.secondary"
																					sx={{ display: "block", mb: 0.5 }}
																				>
																					OUTBOUND REQUEST HEADERS (REDACTED)
																				</Typography>
																				<Paper
																					elevation={0}
																					sx={{
																						p: 1.5,
																						border: `1px solid ${theme.palette.divider}`,
																						borderRadius: 1,
																						maxHeight: 140,
																						overflowY: "auto",
																						bgcolor: alpha(theme.palette.background.default, 0.5),
																					}}
																				>
																					<pre
																						style={{
																							margin: 0,
																							fontFamily: "monospace",
																							fontSize: "0.75rem",
																						}}
																					>
																						{JSON.stringify(httpLog.request?.headers || {}, null, 2)}
																					</pre>
																				</Paper>

																				{httpLog.request?.body !== undefined &&
																					httpLog.request?.body !== null && (
																						<>
																							<Typography
																								variant="caption"
																								fontWeight={700}
																								color="text.secondary"
																								sx={{ display: "block", mt: 1.5, mb: 0.5 }}
																							>
																								REQUEST PAYLOAD / BODY
																							</Typography>
																							<Paper
																								elevation={0}
																								sx={{
																									p: 1.5,
																									border: `1px solid ${theme.palette.divider}`,
																									borderRadius: 1,
																									maxHeight: 160,
																									overflowY: "auto",
																									bgcolor: alpha(
																										theme.palette.background.default,
																										0.5,
																									),
																								}}
																							>
																								<pre
																									style={{
																										margin: 0,
																										fontFamily: "monospace",
																										fontSize: "0.75rem",
																									}}
																								>
																									{typeof httpLog.request?.body === "object"
																										? JSON.stringify(httpLog.request?.body, null, 2)
																										: String(httpLog.request?.body)}
																								</pre>
																							</Paper>
																						</>
																					)}
																			</Grid>

																			{/* Inbound Response Details */}
																			<Grid item xs={12} md={6}>
																				<Stack
																					direction="row"
																					justifyContent="space-between"
																					alignItems="center"
																					sx={{ mb: 0.5 }}
																				>
																					<Typography
																						variant="caption"
																						fontWeight={700}
																						color="text.secondary"
																					>
																						INBOUND RESPONSE BODY
																					</Typography>
																					{httpLog.response?.status_code && (
																						<Typography
																							variant="caption"
																							fontWeight={700}
																							color={
																								httpLog.response.status_code < 300
																									? "success.main"
																									: "error.main"
																							}
																						>
																							HTTP {httpLog.response.status_code}
																						</Typography>
																					)}
																				</Stack>
																				<Paper
																					elevation={0}
																					sx={{
																						p: 1.5,
																						border: `1px solid ${theme.palette.divider}`,
																						borderRadius: 1,
																						maxHeight: 330,
																						overflowY: "auto",
																						bgcolor: alpha(theme.palette.background.default, 0.5),
																					}}
																				>
																					<pre
																						style={{
																							margin: 0,
																							fontFamily: "monospace",
																							fontSize: "0.75rem",
																						}}
																					>
																						{httpLog.response?.body !== undefined
																							? typeof httpLog.response?.body === "object"
																								? JSON.stringify(httpLog.response?.body, null, 2)
																								: String(httpLog.response?.body)
																							: "(No response body)"}
																					</pre>
																				</Paper>
																			</Grid>
																		</Grid>
																	</Stack>
																) : (
																	<Box>
																		<Typography
																			variant="caption"
																			fontWeight={700}
																			color="text.secondary"
																			sx={{ display: "block", mb: 0.5 }}
																		>
																			NODE OUTPUT
																		</Typography>
																		<pre
																			style={{
																				margin: 0,
																				fontFamily: "monospace",
																				fontSize: "0.75rem",
																				maxHeight: 140,
																				overflowY: "auto",
																			}}
																		>
																			{JSON.stringify(st.output, null, 2)}
																		</pre>
																	</Box>
																)}
															</AccordionDetails>
														</Accordion>
													);
												})}
											</Stack>
										</Box>
									)}

									{/* Final Output Accordion */}
									<Accordion
										elevation={0}
										disableGutters
										sx={{
											border: `1px solid ${theme.palette.divider}`,
											borderRadius: 1.5,
											"&:before": { display: "none" },
										}}
									>
										<AccordionSummary expandIcon={<ExpandMore />} sx={{ py: 0.5 }}>
											<Typography variant="caption" fontWeight={700} color="text.secondary">
												FINAL WORKFLOW OUTPUT PAYLOAD
											</Typography>
										</AccordionSummary>
										<AccordionDetails sx={{ p: 1.5, bgcolor: alpha(theme.palette.background.default, 0.5) }}>
											<pre
												style={{
													margin: 0,
													fontFamily: "monospace",
													fontSize: "0.75rem",
													maxHeight: 160,
													overflowY: "auto",
												}}
											>
												{JSON.stringify(r.final_output, null, 2)}
											</pre>
										</AccordionDetails>
									</Accordion>
								</Paper>
							))}
						</Stack>
					)}
				</Paper>
			)}

			{/* Import cURL Dialog */}
			<Dialog open={curlModalOpen} onClose={() => setCurlModalOpen(false)} maxWidth="sm" fullWidth>
				<DialogTitle>Import from cURL Command</DialogTitle>
				<DialogContent dividers>
					<Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
						Paste any standard cURL command. It will be parsed into HTTP Method, URL, Headers, and JSON Body.
					</Typography>
					<TextField
						label="cURL Command"
						fullWidth
						multiline
						rows={8}
						placeholder={`curl -X POST https://devmis.sspa.gos.pk/api/v1/imis/auth/login \\\n  -H "x-api-key: MIS_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"email": "...", "password": "..."}'`}
						value={curlInput}
						onChange={(e) => setCurlInput(e.target.value)}
						slotProps={{
							input: {
								sx: { fontFamily: "monospace", fontSize: "0.82rem" },
							},
						}}
					/>
				</DialogContent>
				<DialogActions>
					<Button onClick={() => setCurlModalOpen(false)}>Cancel</Button>
					<Button variant="contained" onClick={handleApplyCurl} disabled={!curlInput.trim()}>
						Parse & Apply
					</Button>
				</DialogActions>
			</Dialog>

			{/* Add Step Dialog */}
			<Dialog open={addStepOpen} onClose={() => setAddStepOpen(false)} maxWidth="sm" fullWidth>
				<DialogTitle>Add Node to Pipeline</DialogTitle>
				<DialogContent dividers>
					<Stack spacing={2.5} sx={{ pt: 1 }}>
						<TextField
							label="Node Key"
							required
							fullWidth
							size="small"
							value={newStepKey}
							onChange={(e) =>
								setNewStepKey(e.target.value.toLowerCase().replace(/[^a-z0-9_]+/g, "_"))
							}
							helperText="Used in {{nodes.<key>.output}}"
						/>

						<FormControl fullWidth size="small">
							<InputLabel>Node Type</InputLabel>
							<Select
								value={newStepType}
								label="Node Type"
								onChange={(e) => setNewStepType(e.target.value)}
							>
								{NODE_TYPES.map((nt) => (
									<MenuItem key={nt.value} value={nt.value}>
										<Stack direction="row" spacing={1} alignItems="center">
											{nt.icon}
											<span>{nt.label}</span>
										</Stack>
									</MenuItem>
								))}
							</Select>
						</FormControl>
					</Stack>
				</DialogContent>
				<DialogActions>
					<Button onClick={() => setAddStepOpen(false)}>Cancel</Button>
					<Button
						variant="contained"
						disabled={addStepMutation.isPending || !newStepKey.trim()}
						onClick={() => {
							let defaultCfg = {};
							if (newStepType === "start_webhook") {
								defaultCfg = {
									default_payload: {
										source_ticket_id: "IMIS-TICKET-2026-00123",
										benef_cnic: "42201-1234567-1",
										category: "Payments",
										description: "Sample grievance description",
									},
								};
							} else if (newStepType === "code") {
								defaultCfg = {
									code: `# Code Node\n# Access: trigger, nodes, env, crypto\npayload = {\n    "source_ticket_id": trigger.get("source_ticket_id"),\n    "benef_cnic": trigger.get("benef_cnic"),\n}\n# Encrypt with SSPA AES-256-GCM:\nencrypted = crypto.encrypt_sspa_payload(payload, env["MIS_AES_KEY"])\nreturn encrypted\n`,
								};
							} else if (newStepType === "http_request") {
								defaultCfg = {
									method: "POST",
									url: "{{env.MIS_BASE_URL}}/api/v1/imis/complaint/create",
									headers: {
										"Content-Type": "application/json",
										"x-api-key": "{{env.MIS_KEY}}",
										"Authorization": "Bearer {{nodes.login.data.access_token}}",
									},
									body: "{{nodes.encrypt_payload.output}}",
								};
							} else if (newStepType === "aes_encrypt") {
								defaultCfg = {
									key: "{{env.MIS_AES_KEY}}",
									payload: "{{nodes.prepare_payload.output}}",
								};
							} else if (newStepType === "aes_decrypt") {
								defaultCfg = {
									key: "{{env.MIS_AES_KEY}}",
									encrypted_data: "{{nodes.intake_api.data.encrypted_data}}",
								};
							}

							addStepMutation.mutate({
								step_key: newStepKey,
								step_type: newStepType,
								step_order: steps.length + 1,
								config: defaultCfg,
								is_active: true,
							});
						}}
					>
						Add Node
					</Button>
				</DialogActions>
			</Dialog>

			{/* Full Run Execution Drawer / Dialog */}
			<Dialog open={runOpen} onClose={() => setRunOpen(false)} maxWidth="md" fullWidth>
				<DialogTitle>Execute Workflow: {workflow.name}</DialogTitle>
				<DialogContent dividers>
					<Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
						Provide trigger input JSON to run through this workflow pipeline. Step-by-step results will be evaluated and logged.
					</Typography>

					<TextField
						label="Trigger Input JSON"
						fullWidth
						multiline
						rows={7}
						value={runPayload}
						onChange={(e) => setRunPayload(e.target.value)}
						slotProps={{
							input: {
								sx: { fontFamily: "monospace", fontSize: "0.85rem" },
							},
						}}
					/>

					{runWorkflowMutation.isPending && (
						<Box sx={{ py: 4, textAlign: "center" }}>
							<CircularProgress size={32} />
							<Typography variant="body2" sx={{ mt: 1, color: "text.secondary" }}>
								Running pipeline through all steps...
							</Typography>
						</Box>
					)}

					{runResult && (
						<Box sx={{ mt: 3 }}>
							<Alert
								severity={runResult.status === "SUCCESS" ? "success" : "error"}
								sx={{ mb: 2 }}
							>
								Status: <b>{runResult.status}</b> | Duration: <b>{runResult.total_time_ms} ms</b>
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
									maxHeight: 220,
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
						disabled={runWorkflowMutation.isPending}
						onClick={() => {
							let parsed = {};
							try {
								if (runPayload.trim()) {
									parsed = JSON.parse(runPayload);
								}
							} catch (e) {
								showError("Invalid JSON in trigger payload");
								return;
							}
							runWorkflowMutation.mutate(parsed);
						}}
					>
						Execute Workflow
					</Button>
				</DialogActions>
			</Dialog>
		</Box>
	);
}
