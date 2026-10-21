import {
	ArrowBack,
	AutoAwesome,
	KeyOutlined,
	SaveOutlined,
	Storage,
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
	Divider,
	IconButton,
	InputAdornment,
	MenuItem,
	Paper,
	Select,
	Switch,
	TextField,
	ToggleButton,
	ToggleButtonGroup,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import MethodChip, { METHOD_COLORS } from "../components/common/MethodChip";
import MappingEditor from "../components/mappings/MappingEditor";
import MappingPreview from "../components/mappings/MappingPreview";
import {
	buildAutoDescription,
	buildCompleteMappingPayload,
	createMappingRow,
	METHOD_OPTIONS,
	validateMappingForm,
} from "../components/mappings/mappingModel";
import { useSnackbar } from "../context/SnackbarContext";
import { useApiMutation } from "../hooks/useApi";
import endpointService from "../services/endpointService";

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

export function SectionCard({ step, title, caption, action, children, sx }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";

	return (
		<Paper
			elevation={0}
			sx={{
				border: "1px solid",
				borderColor: "divider",
				borderRadius: 3,
				overflow: "hidden",
				backgroundColor: alpha(theme.palette.background.paper, 0.86),
				...sx,
			}}
		>
			<Box
				sx={{
					display: "flex",
					alignItems: "center",
					gap: 1.5,
					px: { xs: 2, sm: 3 },
					py: 1.75,
					borderBottom: "1px solid",
					borderColor: "divider",
					background: `linear-gradient(90deg, ${alpha(theme.palette.primary.main, isDark ? 0.09 : 0.05)} 0%, transparent 60%)`,
				}}
			>
				<Box
					aria-hidden
					sx={{
						width: 34,
						height: 34,
						flexShrink: 0,
						display: "flex",
						alignItems: "center",
						justifyContent: "center",
						borderRadius: "10px",
						border: `1px solid ${alpha(theme.palette.primary.main, 0.32)}`,
						color: "primary.main",
						fontFamily: theme.typography.fontFamilyCode,
						fontSize: "0.72rem",
						fontWeight: 700,
						letterSpacing: "0.04em",
					}}
				>
					{step}
				</Box>
				<Box sx={{ minWidth: 0, flex: 1 }}>
					<Typography variant="subtitle1" sx={{ lineHeight: 1.3 }}>
						{title}
					</Typography>
					{caption && (
						<Typography
							variant="body2"
							sx={{ color: "text.secondary", fontSize: "0.76rem" }}
						>
							{caption}
						</Typography>
					)}
				</Box>
				{action}
			</Box>
			<Box sx={{ px: { xs: 2, sm: 3 }, py: { xs: 2, sm: 2.5 } }}>
				{children}
			</Box>
		</Paper>
	);
}

export function RouteComposer({
	method,
	onMethodChange,
	url,
	onUrlChange,
	urlLabel,
	placeholder,
	error,
	helperText,
}) {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;

	return (
		<TextField
			fullWidth
			label={urlLabel}
			value={url}
			onChange={(event) => onUrlChange(event.target.value)}
			error={Boolean(error)}
			helperText={helperText}
			placeholder={placeholder}
			slotProps={{
				input: {
					startAdornment: (
						<InputAdornment position="start" sx={{ mr: 0 }}>
							<Select
								variant="standard"
								disableUnderline
								value={method}
								onChange={(event) => onMethodChange(event.target.value)}
								aria-label={`${urlLabel} method`}
								sx={{
									fontFamily: codeFont,
									fontWeight: 700,
									fontSize: "0.78rem",
									letterSpacing: "0.03em",
									color: METHOD_COLORS[method] || "text.primary",
									"& .MuiSelect-select": {
										py: 0.35,
										pl: 0.5,
										pr: "22px !important",
									},
								}}
							>
								{METHOD_OPTIONS.map((option) => (
									<MenuItem
										key={option}
										value={option}
										sx={{
											fontFamily: codeFont,
											fontWeight: 600,
											fontSize: "0.78rem",
											color: METHOD_COLORS[option],
										}}
									>
										{option}
									</MenuItem>
								))}
							</Select>
							<Divider
								orientation="vertical"
								flexItem
								sx={{ mx: 1.25, my: 0.8 }}
							/>
						</InputAdornment>
					),
				},
				htmlInput: {
					style: { fontFamily: codeFont, fontSize: "0.84rem" },
					spellCheck: false,
					autoCapitalize: "off",
				},
			}}
		/>
	);
}

export function ProtocolSwitch({ protocol, onChange }) {
	return (
		<ToggleButtonGroup
			size="small"
			exclusive
			value={protocol || "HTTP"}
			onChange={(_event, next) => next && onChange(next)}
			aria-label="Mapping transport"
			sx={{
				"& .MuiToggleButton-root": {
					px: 1.5,
					py: 0.4,
					fontSize: "0.68rem",
					fontFamily: "var(--font-mono)",
					textTransform: "none",
					letterSpacing: "0.03em",
				},
			}}
		>
			<ToggleButton value="HTTP">HTTP</ToggleButton>
			<ToggleButton value="SFTP">SFTP</ToggleButton>
		</ToggleButtonGroup>
	);
}

export function SftpSourceFields({ form, onChange, errors = {} }) {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;
	const [showPassword, setShowPassword] = useState(false);

	const field = (key) => ({
		value: form?.[key] ?? "",
		onChange: (event) => onChange?.(key, event.target.value),
		slotProps: {
			htmlInput: { style: { fontFamily: codeFont, fontSize: "0.84rem" } },
		},
	});

	return (
		<Box
			sx={{
				display: "grid",
				gridTemplateColumns: { xs: "1fr", md: "2fr 1fr" },
				gap: 2,
			}}
		>
			<TextField
				fullWidth
				required
				label="SFTP host"
				placeholder="recorder.example.com"
				error={Boolean(errors.sftpHost)}
				helperText={errors.sftpHost}
				{...field("sftpHost")}
			/>
			<TextField
				fullWidth
				label="Port"
				type="number"
				placeholder="22"
				error={Boolean(errors.sftpPort)}
				helperText={errors.sftpPort}
				slotProps={{
					htmlInput: {
						min: 1,
						max: 65535,
						style: { fontFamily: codeFont, fontSize: "0.84rem" },
					},
				}}
				value={form?.sftpPort ?? ""}
				onChange={(event) => onChange?.("sftpPort", event.target.value)}
			/>
			<TextField
				fullWidth
				label="Username"
				placeholder="mapper"
				autoComplete="off"
				{...field("sftpUsername")}
			/>
			<TextField
				fullWidth
				label="Password"
				type={showPassword ? "text" : "password"}
				placeholder="Leave blank to keep the stored password"
				autoComplete="new-password"
				{...field("sftpPassword")}
				slotProps={{
					htmlInput: { style: { fontFamily: codeFont, fontSize: "0.84rem" } },
					input: {
						endAdornment: (
							<InputAdornment position="end">
								<IconButton
									size="small"
									edge="end"
									onClick={() => setShowPassword((prev) => !prev)}
									aria-label={showPassword ? "Hide SFTP password" : "Show SFTP password"}
								>
									{showPassword ? (
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
			<TextField
				fullWidth
				label="Private key path"
				placeholder="Optional — /home/mapper/.ssh/id_ed25519"
				{...field("sftpPrivateKeyPath")}
			/>
			<TextField
				fullWidth
				required
				label="Remote path"
				placeholder="/recordings"
				error={Boolean(errors.sftpRemotePath)}
				helperText={
					errors.sftpRemotePath ||
					"Directory the gateway lists or reads files from."
				}
				{...field("sftpRemotePath")}
			/>
		</Box>
	);
}

export default function CreateMappingPage() {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const codeFont = theme.typography.fontFamilyCode;
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { showSnackbar } = useSnackbar();

	const [form, setForm] = useState({
		sourceUrl: "",
		sourceMethod: "POST",
		targetUrl: "",
		targetMethod: "POST",
		protocol: "HTTP",
		sftpHost: "",
		sftpPort: "22",
		sftpUsername: "",
		sftpPassword: "",
		sftpPrivateKeyPath: "",
		sftpRemotePath: "/",
		dynamicFilenamePattern: "",
	});
	const [authEnabled, setAuthEnabled] = useState(false);
	const [auth, setAuth] = useState({
		apiId: "",
		apiPassword: "",
		apiAuthUrl: "",
	});
	const [showApiPassword, setShowApiPassword] = useState(false);
	const [mappings, setMappings] = useState(() => [createMappingRow()]);
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
	const isSftp = form.protocol === "SFTP";

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

	const saveMutation = useApiMutation(endpointService.saveCompleteMapping, {
		onSuccess: (data) => {
			queryClient.invalidateQueries({ queryKey: ["endpoints"] });
			setPreviewOpen(false);

			if (data?.isDuplicate) {
				showSnackbar(
					`Saved “${data.endpointCode ?? "endpoint"}” — an identical route already exists, review the registry for duplicates.`,
					"warning",
				);
			} else if (data?.warning) {
				showSnackbar(
					`Mapping saved · ${data.endpointCode ?? "endpoint"}${data.message ? ` — ${data.message}` : ""}`,
					"warning",
				);
			} else {
				showSnackbar(
					`Mapping saved · ${data?.endpointCode ?? "endpoint created"}`,
					"success",
				);
			}
			navigate("/");
		},
		onError: (error) => {
			const detail =
				error?.response?.data?.detail ||
				error?.message ||
				"Could not save the mapping. Try again.";
			showSnackbar(
				typeof detail === "string" ? detail : "Could not save the mapping.",
				"error",
			);
		},
	});

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
					Mapping · New registration
				</Typography>
				<Typography variant="h4" sx={{ mt: 0.5 }}>
					Create mapping
				</Typography>
				<Typography
					variant="body2"
					sx={{ color: "text.secondary", mt: 0.5, maxWidth: 640 }}
				>
					Define where the call arrives, where it is forwarded and how every
					field travels between the two contracts. The gateway picks the mapping
					up as soon as it is saved.
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
						<>
							<Box
								sx={{
									display: "flex",
									alignItems: "center",
									gap: 1,
									mb: 2,
									color: "text.secondary",
								}}
							>
								<Storage sx={{ fontSize: 18, color: "primary.main" }} />
								<Typography variant="body2" sx={{ fontSize: "0.78rem" }}>
									Same credential set the SFTP audio endpoints use. The route
									above serves the remote directory or file.
								</Typography>
							</Box>
							<SftpSourceFields
								form={form}
								onChange={(key, value) => updateForm({ [key]: value })}
								errors={errors}
							/>
						</>
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

					<Typography
						variant="body2"
						sx={{ color: "text.disabled", fontSize: "0.74rem", mt: 2 }}
					>
						Duplicate protection: if an identical route already exists you will
						be warned right after saving.
					</Typography>
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
							{saving ? "Writing to the registry" : "Ready to save"}
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
						{saving ? "Saving…" : "Save mapping"}
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
				isEdit={false}
			/>
		</Box>
	);
}
