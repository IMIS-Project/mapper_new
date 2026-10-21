import {
	ArrowBack,
	AutoAwesome,
	KeyOutlined,
	Refresh,
	SaveOutlined,
	Visibility,
	VisibilityOff,
	VisibilityOutlined,
} from "@mui/icons-material";
import {
	Alert,
	Box,
	Button,
	Chip,
	Collapse,
	IconButton,
	InputAdornment,
	Paper,
	Skeleton,
	Switch,
	TextField,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import MethodChip from "../components/common/MethodChip";
import { ActiveChip } from "../components/endpoints/EndpointCard";
import MappingEditor from "../components/mappings/MappingEditor";
import MappingPreview from "../components/mappings/MappingPreview";
import {
	buildAutoDescription,
	buildCompleteMappingPayload,
	createMappingRow,
	isSftpForm,
	parametersToRows,
	validateMappingForm,
} from "../components/mappings/mappingModel";
import { useSnackbar } from "../context/SnackbarContext";
import { useApiMutation, useApiQuery } from "../hooks/useApi";
import endpointService from "../services/endpointService";
import {
	ProtocolSwitch,
	RouteComposer,
	SectionCard,
	SftpSourceFields,
} from "./CreateMappingPage";

const containerVariants = {
	hidden: {},
	visible: { transition: { staggerChildren: 0.06, delayChildren: 0.02 } },
};

const itemVariants = {
	hidden: { opacity: 0, y: 12 },
	visible: {
		opacity: 1,
		y: 0,
		transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] },
	},
};

function formatDate(value) {
	if (!value) return "—";
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return "—";
	return date.toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
		year: "numeric",
		hour: "2-digit",
		minute: "2-digit",
	});
}

function EditSkeleton() {
	return (
		<Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
			<Box>
				<Skeleton variant="rounded" width={130} height={30} sx={{ mb: 1.5 }} />
				<Skeleton variant="text" width={140} height={18} sx={{ mb: 0.5 }} />
				<Skeleton variant="rounded" width={280} height={40} />
			</Box>
			{[0, 1, 2].map((key) => (
				<Paper
					key={key}
					elevation={0}
					sx={{
						border: "1px solid",
						borderColor: "divider",
						borderRadius: 3,
						overflow: "hidden",
					}}
				>
					<Box
						sx={{
							px: 3,
							py: 2,
							borderBottom: "1px solid",
							borderColor: "divider",
						}}
					>
						<Skeleton variant="text" width={180} height={26} />
					</Box>
					<Box sx={{ px: 3, py: 2.5 }}>
						<Skeleton variant="rounded" width="100%" height={56} />
					</Box>
				</Paper>
			))}
		</Box>
	);
}

function hydrateRouteForm(record) {
	const storedMethod = String(record.method ?? "POST").toUpperCase();
	// Only a route path plus credentials is a true SFTP gateway endpoint;
	// legacy file-mapping rows use an absolute target URL.
	const protocol =
		String(record.protocol ?? "").toUpperCase() === "SFTP" && record.sftp_host
			? "SFTP"
			: "HTTP";
	return {
		sourceUrl: record.source_api_url ?? record.sourceUrl ?? "",
		sourceMethod: String(
			record.source_method ?? record.sourceMethod ?? storedMethod,
		).toUpperCase(),
		targetUrl: record.target_api_url ?? record.targetUrl ?? "",
		targetMethod: String(
			record.target_method ?? record.targetMethod ?? storedMethod,
		).toUpperCase(),
		protocol,
		sftpHost: record.sftp_host ?? "",
		sftpPort: String(record.sftp_port ?? 22),
		sftpUsername: record.sftp_username ?? "",
		// Never hydrate the secret; a blank box keeps the stored password.
		sftpPassword: "",
		sftpPrivateKeyPath: record.sftp_private_key_path ?? "",
		sftpRemotePath: record.sftp_remote_path ?? "/",
		dynamicFilenamePattern: record.dynamic_filename_pattern ?? "",
	};
}

export default function EditMappingPage() {
	const { id } = useParams();
	const navigate = useNavigate();

	const endpointQuery = useApiQuery(
		["endpoint", id],
		() => endpointService.getEndpoint(id),
		{
			enabled: Boolean(id),
		},
	);
	const parametersQuery = useApiQuery(
		["endpoint-parameters", id],
		() => endpointService.getParameters(id),
		{ enabled: Boolean(id) },
	);

	const handleRetry = () => {
		endpointQuery.refetch();
		parametersQuery.refetch();
	};

	const loadError =
		endpointQuery.isError ||
		parametersQuery.isError ||
		!id ||
		(endpointQuery.isSuccess && !endpointQuery.data);
	const loading =
		!loadError && (endpointQuery.isLoading || parametersQuery.isLoading);

	if (loadError) {
		return (
			<Box sx={{ maxWidth: 620, mx: "auto", mt: 4 }}>
				<Alert
					severity="error"
					sx={{ mb: 2 }}
					action={
						<Button
							color="inherit"
							size="small"
							onClick={handleRetry}
							startIcon={<Refresh />}
						>
							Retry
						</Button>
					}
				>
					{!id
						? "No endpoint id provided in the route."
						: endpointQuery.error?.response?.status === 404
							? "This endpoint no longer exists — it may have been deleted."
							: "Could not load this mapping. Check the connection and try again."}
				</Alert>
				<Button
					variant="outlined"
					startIcon={<ArrowBack />}
					onClick={() => navigate("/")}
				>
					Back to endpoints
				</Button>
			</Box>
		);
	}

	if (loading) {
		return (
			<motion.div
				variants={containerVariants}
				initial="hidden"
				animate="visible"
			>
				<EditSkeleton />
			</motion.div>
		);
	}

	return (
		<EditMappingWorkspace
			key={id}
			id={id}
			record={endpointQuery.data}
			parameters={parametersQuery.data}
		/>
	);
}

function EditMappingWorkspace({ id, record, parameters }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const codeFont = theme.typography.fontFamilyCode;
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { showSnackbar } = useSnackbar();

	const [form, setForm] = useState(() => hydrateRouteForm(record));
	const [authEnabled, setAuthEnabled] = useState(() =>
		Boolean(record.api_id || record.api_password || record.api_auth_url),
	);
	const [auth, setAuth] = useState(() => ({
		apiId: record.api_id ?? "",
		apiPassword: record.api_password ?? "",
		apiAuthUrl: record.api_auth_url ?? "",
	}));
	const [showApiPassword, setShowApiPassword] = useState(false);
	const [mappings, setMappings] = useState(() => {
		const rows = parametersToRows(parameters);
		return rows.length ? rows : [createMappingRow()];
	});
	const [errors, setErrors] = useState({});
	const [previewOpen, setPreviewOpen] = useState(false);
	const [previewPayload, setPreviewPayload] = useState(null);

	const autoDescription = useMemo(
		() => buildAutoDescription(form, mappings),
		[form, mappings],
	);
	const enabledCount = mappings.filter((row) => row.enabled).length;
	const filledCount = mappings.filter(
		(row) => row.sourceField.trim() || row.targetField.trim(),
	).length;
	const isSftp = isSftpForm(form);

	const clearError = (key) =>
		setErrors((prev) => {
			if (!prev[key]) return prev;
			const next = { ...prev };
			delete next[key];
			return next;
		});

	const updateForm = (patch) => {
		setForm((prev) => ({ ...prev, ...patch }));
		Object.keys(patch).forEach(clearError);
	};

	const saveMutation = useApiMutation(
		(payload) => endpointService.updateCompleteMapping(id, payload),
		{
			onSuccess: (data) => {
				queryClient.invalidateQueries({ queryKey: ["endpoints"] });
				queryClient.invalidateQueries({ queryKey: ["endpoint", id] });
				queryClient.invalidateQueries({
					queryKey: ["endpoint-parameters", id],
				});
				setPreviewOpen(false);

				if (data?.isDuplicate) {
					showSnackbar(
						`Updated “${data.endpointCode ?? "endpoint"}” — an identical route already exists, review the registry for duplicates.`,
						"warning",
					);
				} else if (data?.warning) {
					showSnackbar(
						`Mapping updated · ${data.endpointCode ?? "endpoint"}${data.message ? ` — ${data.message}` : ""}`,
						"warning",
					);
				} else {
					showSnackbar(
						`Mapping updated · ${data?.endpointCode ?? record?.endpoint_code ?? "endpoint"}`,
						"success",
					);
				}
				navigate("/");
			},
			onError: (error) => {
				const detail =
					error?.response?.data?.detail ||
					error?.message ||
					"Could not save the changes. Try again.";
				showSnackbar(
					typeof detail === "string" ? detail : "Could not save the changes.",
					"error",
				);
			},
		},
	);

	const validateAndBuild = () => {
		const { valid, errors: nextErrors } = validateMappingForm(form, mappings);
		setErrors(nextErrors);
		if (!valid) {
			showSnackbar("Fix the highlighted fields before saving", "error");
			return null;
		}
		return buildCompleteMappingPayload({ form, authEnabled, auth, mappings });
	};

	const handlePreview = () => {
		const payload = validateAndBuild();
		if (!payload) return;
		setPreviewPayload(payload);
		setPreviewOpen(true);
	};

	const handleSave = () => {
		const payload = validateAndBuild();
		if (payload) saveMutation.mutate(payload);
	};

	const saving = saveMutation.isPending;

	return (
		<Box
			component={motion.div}
			variants={containerVariants}
			initial="hidden"
			animate="visible"
			sx={{ display: "flex", flexDirection: "column", gap: 2.5, pb: 3 }}
		>
			{}
			<Box component={motion.div} variants={itemVariants}>
				<Button
					size="small"
					color="inherit"
					startIcon={<ArrowBack sx={{ fontSize: 16 }} />}
					onClick={() => navigate("/")}
					sx={{ mb: 1.5, ml: -1, color: "text.secondary", fontSize: "0.78rem" }}
				>
					Back to endpoints
				</Button>

				<Typography className="mono-label" sx={{ color: "text.disabled" }}>
					Mapping · Edit registration
				</Typography>

				<Box
					sx={{
						display: "flex",
						alignItems: "center",
						gap: 1.25,
						flexWrap: "wrap",
						mt: 0.5,
					}}
				>
					<Typography
						variant="h4"
						sx={{ fontFamily: codeFont, wordBreak: "break-word" }}
					>
						{record?.endpoint_code || "Endpoint"}
					</Typography>
					<ActiveChip active={Boolean(record?.is_active)} />
					<MethodChip method={record?.method} />
					{isSftp && (
						<Chip
							size="small"
							label="SFTP"
							variant="outlined"
							sx={{ fontFamily: codeFont, fontSize: "0.64rem" }}
						/>
					)}
				</Box>

				<Typography
					variant="body2"
					sx={{ color: "text.secondary", mt: 0.75, fontSize: "0.78rem" }}
				>
					ID{" "}
					<span style={{ fontFamily: codeFont }}>
						{String(record?.id ?? id).slice(0, 13)}…
					</span>
					{" · "}created {formatDate(record?.created_at)}
					{record?.description ? ` · ${record.description}` : ""}
				</Typography>
			</Box>

			{}
			<Box component={motion.div} variants={itemVariants}>
				<SectionCard
					step="01"
					title="Internal API"
					caption="The inbound route the gateway listens on."
				>
					<Box sx={{ maxWidth: { md: 640 } }}>
						<RouteComposer
							urlLabel="Internal URL"
							placeholder={
								isSftp ? "/v1/audio/play" : "https://api.example.com/orders"
							}
							method={form.sourceMethod}
							onMethodChange={(next) => updateForm({ sourceMethod: next })}
							url={form.targetUrl}
							onUrlChange={(next) => updateForm({ targetUrl: next })}
							error={errors.targetUrl}
							helperText={
								errors.targetUrl ||
								(isSftp
									? "Gateway path for the SFTP-backed endpoint, e.g. /v1/audio/play (no scheme)."
									: "Full URL or path of the incoming endpoint.")
							}
						/>
					</Box>
				</SectionCard>
			</Box>

			{}
			<Box component={motion.div} variants={itemVariants}>
				<SectionCard
					step="02"
					title={isSftp ? "SFTP source" : "External API"}
					caption={
						isSftp
							? "The gateway reads files straight from this server instead of calling an HTTP upstream."
							: "Where the mapped payload is forwarded."
					}
					action={
						<ProtocolSwitch
							protocol={form.protocol}
							onChange={(next) => updateForm({ protocol: next })}
						/>
					}
				>
					{isSftp ? (
						<SftpSourceFields
							form={form}
							onChange={(key, value) => updateForm({ [key]: value })}
							errors={errors}
						/>
					) : (
						<Box sx={{ maxWidth: { md: 640 } }}>
							<RouteComposer
								urlLabel="External URL"
								placeholder="https://api.partner.example/v2/orders"
								method={form.targetMethod}
								onMethodChange={(next) => updateForm({ targetMethod: next })}
								url={form.sourceUrl}
								onUrlChange={(next) => updateForm({ sourceUrl: next })}
								error={errors.sourceUrl}
								helperText={
									errors.sourceUrl ||
									"Calls are routed by this URL + method pair."
								}
							/>
						</Box>
					)}
				</SectionCard>
			</Box>

			{}
			<Box component={motion.div} variants={itemVariants}>
				<SectionCard
					step="03"
					title="Upstream authentication"
					caption={
						isSftp
							? "Not used — SFTP mappings authenticate with the server credentials above."
							: "Optional — the gateway fetches a bearer token before calling the external API."
					}
					action={
						isSftp ? (
							<Chip
								size="small"
								label="Not used"
								variant="outlined"
								sx={{ fontFamily: codeFont, fontSize: "0.62rem" }}
							/>
						) : (
							<Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
								<Typography
									className="mono-label"
									sx={{
										color: authEnabled ? "success.main" : "text.disabled",
										fontSize: "0.55rem",
									}}
								>
									{authEnabled ? "On" : "Off"}
								</Typography>
								<Switch
									size="small"
									checked={authEnabled}
									onChange={(event) => setAuthEnabled(event.target.checked)}
									slotProps={{
										input: { "aria-label": "Enable upstream authentication" },
									}}
								/>
							</Box>
						)
					}
				>
					{isSftp ? (
						<Box
							sx={{
								display: "flex",
								alignItems: "center",
								gap: 1.25,
								color: "text.disabled",
							}}
						>
							<KeyOutlined sx={{ fontSize: 18 }} />
							<Typography variant="body2" sx={{ fontSize: "0.78rem" }}>
								SFTP mappings are served from the remote server, so there is no
								HTTP upstream token to fetch. Use the credentials in step 02.
							</Typography>
						</Box>
					) : (
						<>
					<Collapse in={authEnabled} unmountOnExit>
						<Box
							sx={{
								display: "grid",
								gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
								gap: 2,
							}}
						>
							<TextField
								fullWidth
								label="API ID"
								value={auth.apiId}
								onChange={(event) =>
									setAuth((prev) => ({ ...prev, apiId: event.target.value }))
								}
								placeholder="client-credentials-id"
								slotProps={{
									htmlInput: {
										style: { fontFamily: codeFont, fontSize: "0.84rem" },
									},
								}}
							/>
							<TextField
								fullWidth
								label="API password"
								type={showApiPassword ? "text" : "password"}
								value={auth.apiPassword}
								onChange={(event) =>
									setAuth((prev) => ({
										...prev,
										apiPassword: event.target.value,
									}))
								}
								placeholder="••••••••••"
								slotProps={{
									htmlInput: {
										style: { fontFamily: codeFont, fontSize: "0.84rem" },
									},
									input: {
										endAdornment: (
											<InputAdornment position="end">
												<IconButton
													size="small"
													edge="end"
													onClick={() => setShowApiPassword((prev) => !prev)}
													aria-label={
														showApiPassword
															? "Hide API password"
															: "Show API password"
													}
												>
													{showApiPassword ? (
														<VisibilityOff fontSize="small" />
													) : (
														<Visibility fontSize="small" />
													)}
												</IconButton>
											</InputAdornment>
										),
									},
								}}
							/>
							<Box sx={{ gridColumn: { md: "1 / -1" } }}>
								<TextField
									fullWidth
									label="API auth URL"
									value={auth.apiAuthUrl}
									onChange={(event) =>
										setAuth((prev) => ({
											...prev,
											apiAuthUrl: event.target.value,
										}))
									}
									placeholder="https://auth.example.com/oauth/token"
									helperText="Token endpoint — called once per request cycle with the credentials above."
									slotProps={{
										htmlInput: {
											style: { fontFamily: codeFont, fontSize: "0.84rem" },
										},
									}}
								/>
							</Box>
						</Box>
					</Collapse>

					{!authEnabled && (
						<Box
							sx={{
								display: "flex",
								alignItems: "center",
								gap: 1.25,
								color: "text.disabled",
							}}
						>
							<KeyOutlined sx={{ fontSize: 18 }} />
							<Typography variant="body2" sx={{ fontSize: "0.78rem" }}>
								No credentials attached — the target is called anonymously. Flip
								the switch to add an API ID, password and token URL.
							</Typography>
						</Box>
					)}
						</>
					)}
				</SectionCard>
			</Box>

			{}
			<Box component={motion.div} variants={itemVariants}>
				<SectionCard
					step="04"
					title="Parameter mappings"
					caption="Field-level transformations applied to every forwarded payload."
					action={
						<Chip
							size="small"
							label={`${enabledCount}/${mappings.length} enabled`}
							sx={{ fontFamily: codeFont, fontSize: "0.64rem" }}
							variant="outlined"
						/>
					}
				>
					{errors.mappings && (
						<Alert severity="error" sx={{ mb: 2, fontSize: "0.8rem" }}>
							{errors.mappings}
						</Alert>
					)}
					<MappingEditor
						mappings={mappings}
						onChange={(next) => {
							setMappings(next);
							clearError("mappings");
						}}
					/>
				</SectionCard>
			</Box>

			{}
			<Box component={motion.div} variants={itemVariants}>
				<SectionCard
					step="05"
					title="Description & review"
					caption="The summary is composed automatically from your mappings."
				>
					<Box
						sx={{
							display: "flex",
							gap: 1.25,
							p: 2,
							borderRadius: 2,
							border: "1px dashed",
							borderColor: alpha(theme.palette.primary.main, 0.4),
							backgroundColor: alpha(
								theme.palette.primary.main,
								isDark ? 0.07 : 0.035,
							),
						}}
					>
						<AutoAwesome
							sx={{
								fontSize: 18,
								color: "primary.main",
								mt: 0.25,
								flexShrink: 0,
							}}
						/>
						<Box sx={{ minWidth: 0 }}>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.53rem", mb: 0.5 }}
							>
								Auto-generated description
							</Typography>
							<Typography
								variant="body2"
								sx={{
									fontFamily: codeFont,
									fontSize: "0.76rem",
									wordBreak: "break-word",
								}}
							>
								{autoDescription ||
									"Fill in the routes and mappings — a description is composed from them automatically."}
							</Typography>
						</Box>
					</Box>

					<Box sx={{ display: "flex", gap: 2.5, flexWrap: "wrap", mt: 2 }}>
						<Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.53rem" }}
							>
								Route
							</Typography>
							<MethodChip method={form.sourceMethod} sx={{ height: 22 }} />
							<Typography sx={{ color: "text.disabled", fontSize: "0.8rem" }}>
								→
							</Typography>
							<MethodChip method={form.targetMethod} sx={{ height: 22 }} />
						</Box>
						<Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.53rem" }}
							>
								Transport
							</Typography>
							<Typography
								variant="body2"
								sx={{ fontFamily: codeFont, fontSize: "0.74rem" }}
							>
								{isSftp
									? `SFTP · ${form.sftpHost || "host not set"}:${form.sftpPort || 22}`
									: "HTTP"}
							</Typography>
						</Box>
						<Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.53rem" }}
							>
								Fields
							</Typography>
							<Typography
								variant="body2"
								sx={{ fontFamily: codeFont, fontSize: "0.74rem" }}
							>
								{filledCount} filled · {enabledCount} enabled
							</Typography>
						</Box>
						<Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.53rem" }}
							>
								Auth
							</Typography>
							<Typography
								variant="body2"
								sx={{ fontFamily: codeFont, fontSize: "0.74rem" }}
							>
								{isSftp
									? "not used"
									: authEnabled
										? "credentials attached"
										: "none"}
							</Typography>
						</Box>
					</Box>
				</SectionCard>
			</Box>

			{}
			<Box
				component={motion.div}
				variants={itemVariants}
				sx={{ position: "sticky", bottom: 0, zIndex: 5, mt: 0.5 }}
			>
				<Paper
					elevation={0}
					sx={{
						display: "flex",
						alignItems: "center",
						gap: 1.5,
						flexWrap: "wrap",
						px: { xs: 2, sm: 2.5 },
						py: 1.5,
						borderRadius: 3,
						border: "1px solid",
						borderColor: "divider",
						backgroundColor: alpha(theme.palette.background.paper, 0.92),
						backdropFilter: "blur(12px)",
						boxShadow: isDark
							? "0 18px 40px rgba(0, 0, 0, 0.45)"
							: "0 18px 40px rgba(16, 31, 51, 0.12)",
					}}
				>
					<Box sx={{ minWidth: 0, flex: 1 }}>
						<Typography
							className="mono-label"
							sx={{ color: "text.disabled", fontSize: "0.52rem" }}
						>
							{saving ? "Writing to the registry" : "Editing existing mapping"}
						</Typography>
						<Typography
							variant="body2"
							sx={{
								color: "text.secondary",
								fontSize: "0.78rem",
								whiteSpace: "nowrap",
								overflow: "hidden",
								textOverflow: "ellipsis",
							}}
						>
							{isSftp ? "SFTP" : form.sourceMethod} → {form.targetMethod} ·{" "}
							{enabledCount} enabled of {mappings.length} rows
						</Typography>
					</Box>

					<Button
						variant="outlined"
						startIcon={<VisibilityOutlined sx={{ fontSize: 18 }} />}
						onClick={handlePreview}
						disabled={saving}
					>
						Preview
					</Button>
					<Button
						variant="contained"
						startIcon={<SaveOutlined sx={{ fontSize: 18 }} />}
						onClick={handleSave}
						disabled={saving}
					>
						{saving ? "Saving…" : "Save changes"}
					</Button>
				</Paper>
			</Box>

			<MappingPreview
				open={previewOpen}
				onClose={() => setPreviewOpen(false)}
				onConfirm={() => {
					const payload = validateAndBuild() ?? previewPayload;
					if (payload) saveMutation.mutate(payload);
				}}
				saving={saving}
				payload={previewPayload}
				isEdit
			/>
		</Box>
	);
}
