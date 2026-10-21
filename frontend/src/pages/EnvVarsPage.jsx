import {
	Add,
	ContentCopy,
	DeleteOutline,
	EditOutlined,
	Key,
	Lock,
	Refresh,
	Search,
	Visibility,
	VisibilityOff,
} from "@mui/icons-material";
import {
	Alert,
	Box,
	Button,
	Chip,
	CircularProgress,
	Dialog,
	DialogActions,
	DialogContent,
	DialogTitle,
	FormControlLabel,
	IconButton,
	InputAdornment,
	Paper,
	Stack,
	Switch,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableRow,
	TextField,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSnackbar } from "../context/SnackbarContext";
import envVarService from "../services/envVarService";

export default function EnvVarsPage() {
	const theme = useTheme();
	const queryClient = useQueryClient();
	const { showSuccess, showError } = useSnackbar();

	const [unmaskSecrets, setUnmaskSecrets] = useState(false);
	const [searchQuery, setSearchQuery] = useState("");
	const [modalOpen, setModalOpen] = useState(false);
	const [editingVar, setEditingVar] = useState(null);

	const [formData, setFormData] = useState({
		key_name: "",
		value: "",
		is_secret: true,
		category: "MIS_GRM",
		description: "",
	});

	const { data: variables = [], isLoading, isFetching, refetch } = useQuery({
		queryKey: ["env-variables", unmaskSecrets],
		queryFn: () => envVarService.getVariables(unmaskSecrets),
	});

	const saveMutation = useMutation({
		mutationFn: (data) => envVarService.saveVariable(data),
		onSuccess: () => {
			showSuccess("Variable saved successfully");
			queryClient.invalidateQueries({ queryKey: ["env-variables"] });
			setModalOpen(false);
		},
		onError: (err) => {
			showError(err.response?.data?.detail || err.message || "Failed to save variable");
		},
	});

	const deleteMutation = useMutation({
		mutationFn: (id) => envVarService.deleteVariable(id),
		onSuccess: () => {
			showSuccess("Variable deleted");
			queryClient.invalidateQueries({ queryKey: ["env-variables"] });
		},
		onError: (err) => {
			showError(err.response?.data?.detail || err.message || "Failed to delete variable");
		},
	});

	const handleOpenCreate = () => {
		setEditingVar(null);
		setFormData({
			key_name: "",
			value: "",
			is_secret: true,
			category: "MIS_GRM",
			description: "",
		});
		setModalOpen(true);
	};

	const handleOpenEdit = (v) => {
		setEditingVar(v);
		setFormData({
			key_name: v.key_name,
			value: v.is_secret && !unmaskSecrets ? "••••••••" : v.value,
			is_secret: v.is_secret,
			category: v.category || "MIS_GRM",
			description: v.description || "",
		});
		setModalOpen(true);
	};

	const handleSubmit = (e) => {
		e.preventDefault();
		if (!formData.key_name.trim()) return;
		saveMutation.mutate(formData);
	};

	const copyVariableRef = (key) => {
		const snippet = `{{env.${key}}}`;
		navigator.clipboard.writeText(snippet);
		showSuccess(`Copied ${snippet} to clipboard`);
	};

	const filteredVars = useMemo(() => {
		const q = searchQuery.toLowerCase().trim();
		if (!q) return variables;
		return variables.filter(
			(v) =>
				v.key_name.toLowerCase().includes(q) ||
				(v.category && v.category.toLowerCase().includes(q)) ||
				(v.description && v.description.toLowerCase().includes(q)),
		);
	}, [variables, searchQuery]);

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
						<Key color="primary" /> Environment & Global Variables
					</Typography>
					<Typography variant="body2" color="text.secondary">
						Manage secure credentials, endpoints, and symmetric AES keys referenced across workflow steps via <code style={{ color: theme.palette.primary.main }}>{"{{env.KEY_NAME}}"}</code>.
					</Typography>
				</Box>

				<Stack direction="row" spacing={1.5} alignItems="center">
					<FormControlLabel
						control={
							<Switch
								size="small"
								checked={unmaskSecrets}
								onChange={(e) => setUnmaskSecrets(e.target.checked)}
							/>
						}
						label={
							<Typography variant="body2" sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
								{unmaskSecrets ? <Visibility fontSize="inherit" /> : <VisibilityOff fontSize="inherit" />}
								Reveal Values
							</Typography>
						}
					/>
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
						onClick={handleOpenCreate}
					>
						Add Variable
					</Button>
				</Stack>
			</Stack>

			{/* Search & Stats Bar */}
			<Paper
				elevation={0}
				sx={{
					p: 2,
					mb: 3,
					border: `1px solid ${theme.palette.divider}`,
					borderRadius: 2,
					display: "flex",
					flexDirection: { xs: "column", sm: "row" },
					gap: 2,
					alignItems: "center",
					justifyContent: "space-between",
				}}
			>
				<TextField
					size="small"
					placeholder="Search variables by name, category, or description..."
					value={searchQuery}
					onChange={(e) => setSearchQuery(e.target.value)}
					sx={{ minWidth: { xs: "100%", sm: 360 } }}
					slotProps={{
						input: {
							startAdornment: (
								<InputAdornment position="start">
									<Search fontSize="small" />
								</InputAdornment>
							),
						},
					}}
				/>

				<Typography variant="caption" color="text.secondary">
					Showing <b>{filteredVars.length}</b> of <b>{variables.length}</b> variables
				</Typography>
			</Paper>

			{/* Variables Table */}
			<TableContainer
				component={Paper}
				elevation={0}
				sx={{ border: `1px solid ${theme.palette.divider}`, borderRadius: 2 }}
			>
				<Table size="medium">
					<TableHead sx={{ bgcolor: alpha(theme.palette.primary.main, 0.04) }}>
						<TableRow>
							<TableCell sx={{ fontWeight: 600 }}>Variable Key</TableCell>
							<TableCell sx={{ fontWeight: 600 }}>Category</TableCell>
							<TableCell sx={{ fontWeight: 600 }}>Value</TableCell>
							<TableCell sx={{ fontWeight: 600 }}>Description</TableCell>
							<TableCell sx={{ fontWeight: 600, width: 120 }} align="right">
								Actions
							</TableCell>
						</TableRow>
					</TableHead>
					<TableBody>
						{isLoading ? (
							<TableRow>
								<TableCell colSpan={5} align="center" sx={{ py: 6 }}>
									<CircularProgress size={28} />
									<Typography variant="body2" sx={{ mt: 1, color: "text.secondary" }}>
										Loading variables...
									</Typography>
								</TableCell>
							</TableRow>
						) : filteredVars.length === 0 ? (
							<TableRow>
								<TableCell colSpan={5} align="center" sx={{ py: 6 }}>
									<Typography variant="body2" color="text.secondary">
										No environment variables found. Click "Add Variable" to create one.
									</Typography>
								</TableCell>
							</TableRow>
						) : (
							filteredVars.map((v) => (
								<TableRow key={v.id} hover>
									<TableCell>
										<Stack direction="row" alignItems="center" spacing={1}>
											<Typography
												variant="body2"
												fontWeight={700}
												sx={{ fontFamily: "monospace", color: "primary.main" }}
											>
												{v.key_name}
											</Typography>
											<Tooltip title={`Copy expression: {{env.${v.key_name}}}`}>
												<IconButton
													size="small"
													onClick={() => copyVariableRef(v.key_name)}
												>
													<ContentCopy fontSize="inherit" />
												</IconButton>
											</Tooltip>
										</Stack>
									</TableCell>

									<TableCell>
										<Chip
											label={v.category || "GENERAL"}
											size="small"
											variant="outlined"
											sx={{ fontSize: "0.75rem", fontWeight: 600 }}
										/>
									</TableCell>

									<TableCell>
										<Stack direction="row" alignItems="center" spacing={1}>
											{v.is_secret && (
												<Tooltip title="Encrypted at rest">
													<Lock fontSize="inherit" sx={{ color: "warning.main" }} />
												</Tooltip>
											)}
											<Typography
												variant="body2"
												sx={{
													fontFamily: "monospace",
													wordBreak: "break-all",
													color: v.is_secret && !unmaskSecrets ? "text.secondary" : "text.primary",
												}}
											>
												{v.value}
											</Typography>
										</Stack>
									</TableCell>

									<TableCell>
										<Typography variant="body2" color="text.secondary" sx={{ maxWidth: 300 }}>
											{v.description || "—"}
										</Typography>
									</TableCell>

									<TableCell align="right">
										<Stack direction="row" spacing={0.5} justifyContent="flex-end">
											<Tooltip title="Edit Variable">
												<IconButton size="small" onClick={() => handleOpenEdit(v)}>
													<EditOutlined fontSize="small" />
												</IconButton>
											</Tooltip>
											<Tooltip title="Delete Variable">
												<IconButton
													size="small"
													color="error"
													onClick={() => {
														if (window.confirm(`Delete variable ${v.key_name}?`)) {
															deleteMutation.mutate(v.id);
														}
													}}
												>
													<DeleteOutline fontSize="small" />
												</IconButton>
											</Tooltip>
										</Stack>
									</TableCell>
								</TableRow>
							))
						)}
					</TableBody>
				</Table>
			</TableContainer>

			{/* Modal Dialog for Upsert */}
			<Dialog open={modalOpen} onClose={() => setModalOpen(false)} maxWidth="sm" fullWidth>
				<form onSubmit={handleSubmit}>
					<DialogTitle>
						{editingVar ? `Edit ${editingVar.key_name}` : "Add Environment Variable"}
					</DialogTitle>
					<DialogContent dividers>
						<Stack spacing={2.5} sx={{ pt: 1 }}>
							<TextField
								label="Key Name"
								required
								fullWidth
								size="small"
								disabled={!!editingVar}
								value={formData.key_name}
								onChange={(e) =>
									setFormData({
										...formData,
										key_name: e.target.value.toUpperCase().replace(/\s+/g, "_"),
									})
								}
								helperText="Identifier used in {{env.KEY_NAME}}"
							/>

							<TextField
								label="Category"
								fullWidth
								size="small"
								value={formData.category}
								onChange={(e) => setFormData({ ...formData, category: e.target.value })}
								helperText="Group (e.g. MIS_GRM, BANK, AUTH, GENERAL)"
							/>

							<TextField
								label="Value"
								required
								fullWidth
								size="small"
								multiline
								rows={2}
								value={formData.value}
								onChange={(e) => setFormData({ ...formData, value: e.target.value })}
								helperText={
									editingVar && formData.value === "••••••••"
										? "Leave as •••••••• to keep current encrypted secret"
										: "Raw string value or key"
								}
							/>

							<FormControlLabel
								control={
									<Switch
										checked={formData.is_secret}
										onChange={(e) =>
											setFormData({ ...formData, is_secret: e.target.checked })
										}
									/>
								}
								label="Mask as Secret (Encrypted at rest)"
							/>

							<TextField
								label="Description"
								fullWidth
								size="small"
								multiline
								rows={2}
								value={formData.description}
								onChange={(e) =>
									setFormData({ ...formData, description: e.target.value })
								}
								placeholder="Optional notes or documentation for this variable"
							/>
						</Stack>
					</DialogContent>
					<DialogActions>
						<Button onClick={() => setModalOpen(false)}>Cancel</Button>
						<Button type="submit" variant="contained" disabled={saveMutation.isPending}>
							{saveMutation.isPending ? "Saving..." : "Save Variable"}
						</Button>
					</DialogActions>
				</form>
			</Dialog>
		</Box>
	);
}
