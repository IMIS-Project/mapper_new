import {
	Add,
	Api,
	Block,
	CheckCircleOutline,
	Close,
	DeleteOutline,
	GridView,
	Refresh,
	Search,
	SearchOff,
	SyncAlt,
	TableRows,
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
	FormControl,
	IconButton,
	InputAdornment,
	MenuItem,
	Paper,
	Select,
	Skeleton,
	TextField,
	ToggleButton,
	ToggleButtonGroup,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import EndpointList from "../components/endpoints/EndpointList";
import { useSnackbar } from "../context/SnackbarContext";
import { useApiMutation, useApiQuery } from "../hooks/useApi";
import endpointService from "../services/endpointService";

const VIEW_STORAGE_KEY = "endpoints-view";

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

function StatTile({ label, value, icon, accent, active, onClick }) {
	const theme = useTheme();
	const codeFont = theme.typography.fontFamilyCode;

	return (
		<Paper
			elevation={0}
			onClick={onClick}
			sx={{
				p: 2,
				borderRadius: 3,
				border: "1px solid",
				borderColor: active ? alpha(accent, 0.55) : "divider",
				backgroundColor: alpha(theme.palette.background.paper, 0.86),
				cursor: onClick ? "pointer" : "default",
				transition: "border-color 0.16s ease, transform 0.16s ease",
				"&:hover": onClick
					? { borderColor: alpha(accent, 0.45), transform: "translateY(-1px)" }
					: undefined,
			}}
		>
			<Box
				sx={{
					display: "flex",
					alignItems: "center",
					justifyContent: "space-between",
					mb: 0.75,
				}}
			>
				<Typography
					className="mono-label"
					sx={{ color: "text.disabled", fontSize: "0.52rem" }}
				>
					{label}
				</Typography>
				<Box
					sx={{
						width: 26,
						height: 26,
						borderRadius: "8px",
						display: "flex",
						alignItems: "center",
						justifyContent: "center",
						color: accent,
						backgroundColor: alpha(accent, 0.12),
						"& svg": { fontSize: 15 },
					}}
				>
					{icon}
				</Box>
			</Box>
			<Typography
				sx={{
					fontFamily: codeFont,
					fontSize: "1.5rem",
					fontWeight: 700,
					lineHeight: 1.1,
					letterSpacing: "-0.02em",
				}}
			>
				{String(value).padStart(2, "0")}
			</Typography>
		</Paper>
	);
}

function EmptyRegistry({ onCreate }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const ink = isDark ? "#e7eef9" : "#101f33";
	const line = alpha(ink, isDark ? 0.32 : 0.24);
	const nodeBg = alpha(theme.palette.background.paper, 0.96);
	const nodeStroke = alpha(theme.palette.primary.main, 0.45);
	const routePath = "M108 76 C 148 26, 184 126, 224 76";

	return (
		<Paper
			elevation={0}
			sx={{
				position: "relative",
				overflow: "hidden",
				border: "1px dashed",
				borderColor: "divider",
				borderRadius: 3,
				py: { xs: 6, sm: 8 },
				px: 3,
				textAlign: "center",
				backgroundColor: alpha(theme.palette.background.paper, 0.62),
				"@keyframes endpointDashFlow": { to: { strokeDashoffset: -26 } },
			}}
		>
			<Box
				className="blueprint-grid"
				aria-hidden
				sx={{
					position: "absolute",
					inset: 0,
					opacity: isDark ? 0.45 : 0.75,
					maskImage:
						"radial-gradient(ellipse at center, black 0%, transparent 74%)",
					WebkitMaskImage:
						"radial-gradient(ellipse at center, black 0%, transparent 74%)",
				}}
			/>

			<Box
				sx={{
					position: "relative",
					display: "flex",
					flexDirection: "column",
					alignItems: "center",
				}}
			>
				<svg
					width="332"
					height="152"
					viewBox="0 0 332 152"
					fill="none"
					role="img"
					aria-label="Illustration of an internal-to-external route"
					style={{ maxWidth: "100%", height: "auto" }}
				>
					<defs>
						<linearGradient id="endpointRouteGrad" x1="0" y1="0" x2="1" y2="0">
							<stop offset="0%" stopColor="#1976d2" />
							<stop offset="100%" stopColor="#9c27b0" />
						</linearGradient>
					</defs>

					{}
					<rect
						x="10"
						y="46"
						width="98"
						height="60"
						rx="12"
						fill={nodeBg}
						stroke={nodeStroke}
						strokeWidth="1.2"
					/>
					<text
						x="59"
						y="74"
						textAnchor="middle"
						fontFamily="var(--font-mono)"
						fontSize="11"
						fontWeight="700"
						fill={ink}
						letterSpacing="1.5"
					>
						SRC
					</text>
					<rect x="26" y="84" width="66" height="4" rx="2" fill={line} />
					<rect
						x="26"
						y="93"
						width="42"
						height="4"
						rx="2"
						fill={line}
						opacity="0.55"
					/>

					{}
					<path
						d={routePath}
						stroke="url(#endpointRouteGrad)"
						strokeWidth="1.6"
						strokeDasharray="6 7"
						strokeLinecap="round"
						opacity="0.85"
						style={{ animation: "endpointDashFlow 1.5s linear infinite" }}
					/>
					<circle r="4.2" fill="#1976d2">
						<animateMotion
							dur="2.6s"
							repeatCount="indefinite"
							path={routePath}
						/>
					</circle>
					<circle r="3" fill="#9c27b0" opacity="0.85">
						<animateMotion
							dur="2.6s"
							begin="1.3s"
							repeatCount="indefinite"
							path={routePath}
						/>
					</circle>

					{}
					<rect
						x="224"
						y="46"
						width="98"
						height="60"
						rx="12"
						fill={nodeBg}
						stroke={nodeStroke}
						strokeWidth="1.2"
					/>
					<text
						x="273"
						y="74"
						textAnchor="middle"
						fontFamily="var(--font-mono)"
						fontSize="11"
						fontWeight="700"
						fill={ink}
						letterSpacing="1.5"
					>
						TGT
					</text>
					<rect x="240" y="84" width="66" height="4" rx="2" fill={line} />
					<rect
						x="240"
						y="93"
						width="42"
						height="4"
						rx="2"
						fill={line}
						opacity="0.55"
					/>
				</svg>

				<Typography variant="h6" sx={{ mt: 1.5 }}>
					No endpoints registered yet
				</Typography>
				<Typography
					variant="body2"
					sx={{ color: "text.secondary", maxWidth: 440, mt: 0.75, mb: 3 }}
				>
					Register your first internal → external route and the gateway will start
					proxy-ing calls with field-level transformation and full call logging.
				</Typography>
				<Button variant="contained" startIcon={<Add />} onClick={onCreate}>
					Create your first mapping
				</Button>
			</Box>
		</Paper>
	);
}

function NoResults({ onClear }) {
	const theme = useTheme();

	return (
		<Paper
			elevation={0}
			sx={{
				border: "1px dashed",
				borderColor: "divider",
				borderRadius: 3,
				py: 6,
				px: 3,
				textAlign: "center",
				backgroundColor: alpha(theme.palette.background.paper, 0.62),
			}}
		>
			<Box
				sx={{
					width: 52,
					height: 52,
					borderRadius: "14px",
					mx: "auto",
					mb: 2,
					display: "flex",
					alignItems: "center",
					justifyContent: "center",
					border: "1px solid",
					borderColor: "divider",
					color: "text.disabled",
				}}
			>
				<SearchOff />
			</Box>
			<Typography variant="subtitle1">
				No endpoints match your filters
			</Typography>
			<Typography variant="body2" sx={{ color: "text.secondary", mb: 2.5 }}>
				Try a different search term, method or status.
			</Typography>
			<Button variant="outlined" size="small" onClick={onClear}>
				Clear filters
			</Button>
		</Paper>
	);
}

function RegistrySkeleton() {
	return (
		<Box>
			<Box
				sx={{
					display: "grid",
					gridTemplateColumns: { xs: "repeat(2, 1fr)", md: "repeat(4, 1fr)" },
					gap: 1.5,
					mb: 2,
				}}
			>
				{[0, 1, 2, 3].map((key) => (
					<Paper
						key={key}
						elevation={0}
						sx={{
							border: "1px solid",
							borderColor: "divider",
							borderRadius: 3,
							p: 2,
						}}
					>
						<Skeleton variant="text" width="55%" height={14} />
						<Skeleton
							variant="rounded"
							width="40%"
							height={30}
							sx={{ mt: 0.5 }}
						/>
					</Paper>
				))}
			</Box>
			<Paper
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
						px: 2,
						py: 1.5,
						borderBottom: "1px solid",
						borderColor: "divider",
						display: "flex",
						gap: 2,
					}}
				>
					<Skeleton variant="rounded" width={220} height={34} />
					<Box sx={{ flex: 1 }} />
					<Skeleton variant="rounded" width={120} height={34} />
				</Box>
				{[...Array(6)].map((_, index) => (
					<Box
						key={index}
						sx={{
							px: 2,
							py: 1.5,
							display: "flex",
							alignItems: "center",
							gap: 2,
							borderBottom: index < 5 ? "1px solid" : "none",
							borderColor: "divider",
						}}
					>
						<Skeleton variant="rounded" width={140} height={20} />
						<Skeleton variant="rounded" sx={{ flex: 1 }} height={20} />
						<Skeleton variant="rounded" width={70} height={20} />
						<Skeleton variant="rounded" width={90} height={20} />
					</Box>
				))}
			</Paper>
		</Box>
	);
}

export default function EndpointsPage() {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const codeFont = theme.typography.fontFamilyCode;
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { showSnackbar } = useSnackbar();

	const { data, isLoading, isError, error, refetch, isFetching } = useApiQuery(
		["endpoints"],
		endpointService.getEndpoints,
	);

	const endpoints = useMemo(
		() => (Array.isArray(data) ? data : (data?.items ?? [])),
		[data],
	);

	const [search, setSearch] = useState("");
	const [methodFilter, setMethodFilter] = useState("ALL");
	const [statusFilter, setStatusFilter] = useState("ALL");
	const [view, setView] = useState(
		() => localStorage.getItem(VIEW_STORAGE_KEY) || "table",
	);
	const [pendingDelete, setPendingDelete] = useState(null);

	useEffect(() => {
		localStorage.setItem(VIEW_STORAGE_KEY, view);
	}, [view]);

	const stats = useMemo(() => {
		const total = endpoints.length;
		const active = endpoints.filter((item) => item.is_active).length;
		const methods = new Set(
			endpoints
				.map((item) => String(item.method ?? "").toUpperCase())
				.filter(Boolean),
		).size;
		return { total, active, inactive: total - active, methods };
	}, [endpoints]);

	const methodOptions = useMemo(
		() =>
			Array.from(
				new Set(
					endpoints
						.map((item) => String(item.method ?? "").toUpperCase())
						.filter(Boolean),
				),
			).sort(),
		[endpoints],
	);

	const filtered = useMemo(() => {
		const query = search.trim().toLowerCase();
		return endpoints.filter((item) => {
			if (
				methodFilter !== "ALL" &&
				String(item.method ?? "").toUpperCase() !== methodFilter
			) {
				return false;
			}
			if (statusFilter === "ACTIVE" && !item.is_active) return false;
			if (statusFilter === "INACTIVE" && item.is_active) return false;
			if (!query) return true;
			return [
				item.endpoint_code,
				item.source_api_url,
				item.target_api_url,
				item.description,
			].some((value) =>
				String(value ?? "")
					.toLowerCase()
					.includes(query),
			);
		});
	}, [endpoints, search, methodFilter, statusFilter]);

	const filtersActive =
		Boolean(search.trim()) || methodFilter !== "ALL" || statusFilter !== "ALL";

	const clearFilters = () => {
		setSearch("");
		setMethodFilter("ALL");
		setStatusFilter("ALL");
	};

	const toggleMutation = useApiMutation(
		({ endpointId, nextActive }) =>
			endpointService.updateEndpoint(endpointId, { is_active: nextActive }),
		{
			onMutate: async ({ endpointId, nextActive }) => {
				await queryClient.cancelQueries({ queryKey: ["endpoints"] });
				const previous = queryClient.getQueryData(["endpoints"]);
				queryClient.setQueryData(["endpoints"], (old) =>
					Array.isArray(old)
						? old.map((item) =>
								item.id === endpointId
									? { ...item, is_active: nextActive }
									: item,
							)
						: old,
				);
				return { previous };
			},
			onError: (mutationError, _variables, context) => {
				if (context?.previous !== undefined) {
					queryClient.setQueryData(["endpoints"], context.previous);
				}
				const detail =
					mutationError?.response?.data?.detail ||
					mutationError?.message ||
					"Could not update the endpoint status.";
				showSnackbar(
					typeof detail === "string"
						? detail
						: "Could not update the endpoint status.",
					"error",
				);
			},
			onSuccess: (_response, variables) => {
				showSnackbar(
					variables.nextActive ? "Endpoint activated" : "Endpoint deactivated",
					"success",
				);
			},
			onSettled: () => {
				queryClient.invalidateQueries({ queryKey: ["endpoints"] });
			},
		},
	);

	const deleteMutation = useApiMutation(
		(endpointId) => endpointService.deleteEndpoint(endpointId),
		{
			onSuccess: (response) => {
				queryClient.invalidateQueries({ queryKey: ["endpoints"] });
				setPendingDelete(null);
				showSnackbar(
					response?.message ||
						`Endpoint “${pendingDelete?.endpoint_code ?? "endpoint"}” deleted`,
					"success",
				);
			},
			onError: (mutationError) => {
				const detail =
					mutationError?.response?.data?.detail ||
					mutationError?.message ||
					"Could not delete the endpoint.";
				showSnackbar(
					typeof detail === "string"
						? detail
						: "Could not delete the endpoint.",
					"error",
				);
			},
		},
	);

	const handleToggle = (endpoint) => {
		if (!endpoint?.id) return;
		toggleMutation.mutate({
			endpointId: endpoint.id,
			nextActive: !endpoint.is_active,
		});
	};

	const confirmDelete = () => {
		if (pendingDelete?.id) deleteMutation.mutate(pendingDelete.id);
	};

	const hasEndpoints = endpoints.length > 0;

	return (
		<Box
			component={motion.div}
			variants={containerVariants}
			initial="hidden"
			animate="visible"
			sx={{ display: "flex", flexDirection: "column", gap: 2.5, pb: 3 }}
		>
			{}
			<Box
				component={motion.div}
				variants={itemVariants}
				sx={{
					display: "flex",
					alignItems: "flex-end",
					justifyContent: "space-between",
					gap: 2,
					flexWrap: "wrap",
				}}
			>
				<Box>
					<Typography className="mono-label" sx={{ color: "text.disabled" }}>
						Workspace · Endpoint registry
					</Typography>
					<Box
						sx={{ display: "flex", alignItems: "center", gap: 1.25, mt: 0.5 }}
					>
						<Typography variant="h4">API Endpoints</Typography>
						{!isLoading && (
							<Chip
								size="small"
								label={`${stats.total} registered`}
								sx={{
									fontFamily: codeFont,
									fontSize: "0.66rem",
									color: "text.secondary",
									backgroundColor: alpha(
										theme.palette.text.primary,
										isDark ? 0.08 : 0.05,
									),
								}}
							/>
						)}
					</Box>
					<Typography
						variant="body2"
						sx={{ color: "text.secondary", mt: 0.5, maxWidth: 620 }}
					>
						Every route the gateway can serve — inspect, activate or retire
						mappings, and jump into the editor to adjust field transformations.
					</Typography>
				</Box>

				<Button
					variant="contained"
					startIcon={<Add />}
					onClick={() => navigate("/create-mapping")}
					sx={{ flexShrink: 0 }}
				>
					Create mapping
				</Button>
			</Box>

			{isLoading ? (
				<RegistrySkeleton />
			) : isError ? (
				<Alert
					severity="error"
					action={
						<Button
							color="inherit"
							size="small"
							onClick={() => refetch()}
							startIcon={<Refresh />}
						>
							Retry
						</Button>
					}
				>
					Could not load endpoints
					{error?.response?.status ? ` (HTTP ${error.response.status})` : ""}.
					Check the backend connection and try again.
				</Alert>
			) : (
				<Box
					component={motion.div}
					variants={itemVariants}
					sx={{ display: "flex", flexDirection: "column", gap: 2 }}
				>
					{}
					<Box
						sx={{
							display: "grid",
							gridTemplateColumns: {
								xs: "repeat(2, 1fr)",
								md: "repeat(4, 1fr)",
							},
							gap: 1.5,
						}}
					>
						<StatTile
							label="Registered"
							value={stats.total}
							icon={<Api />}
							accent={theme.palette.primary.main}
							onClick={filtersActive ? clearFilters : undefined}
						/>
						<StatTile
							label="Active"
							value={stats.active}
							icon={<CheckCircleOutline />}
							accent={theme.palette.success.main}
							active={statusFilter === "ACTIVE"}
							onClick={() =>
								setStatusFilter((prev) =>
									prev === "ACTIVE" ? "ALL" : "ACTIVE",
								)
							}
						/>
						<StatTile
							label="Inactive"
							value={stats.inactive}
							icon={<Block />}
							accent={theme.palette.warning.main}
							active={statusFilter === "INACTIVE"}
							onClick={() =>
								setStatusFilter((prev) =>
									prev === "INACTIVE" ? "ALL" : "INACTIVE",
								)
							}
						/>
						<StatTile
							label="Methods in use"
							value={stats.methods}
							icon={<SyncAlt />}
							accent={theme.palette.secondary.main}
						/>
					</Box>

					{}
					{hasEndpoints && (
						<Paper
							elevation={0}
							sx={{
								display: "flex",
								alignItems: "center",
								gap: 1.25,
								flexWrap: "wrap",
								p: 1.5,
								borderRadius: 3,
								border: "1px solid",
								borderColor: "divider",
								backgroundColor: alpha(theme.palette.background.paper, 0.86),
								"@keyframes registrySpin": {
									from: { transform: "rotate(0deg)" },
									to: { transform: "rotate(360deg)" },
								},
							}}
						>
							<TextField
								size="small"
								placeholder="Search code, URL or description…"
								value={search}
								onChange={(event) => setSearch(event.target.value)}
								sx={{ flex: 1, minWidth: 220, maxWidth: 420 }}
								slotProps={{
									input: {
										startAdornment: (
											<InputAdornment position="start">
												<Search sx={{ fontSize: 18, color: "text.disabled" }} />
											</InputAdornment>
										),
										endAdornment: search ? (
											<InputAdornment position="end">
												<IconButton
													size="small"
													edge="end"
													onClick={() => setSearch("")}
													aria-label="Clear search"
												>
													<Close sx={{ fontSize: 16 }} />
												</IconButton>
											</InputAdornment>
										) : null,
									},
								}}
							/>

							<FormControl size="small" sx={{ minWidth: 138 }}>
								<Select
									value={methodFilter}
									onChange={(event) => setMethodFilter(event.target.value)}
									inputProps={{ "aria-label": "Filter by method" }}
									sx={{
										fontFamily: codeFont,
										fontSize: "0.78rem",
										fontWeight: 600,
									}}
								>
									<MenuItem
										value="ALL"
										sx={{ fontFamily: codeFont, fontSize: "0.78rem" }}
									>
										All methods
									</MenuItem>
									{methodOptions.map((method) => (
										<MenuItem
											key={method}
											value={method}
											sx={{ fontFamily: codeFont, fontSize: "0.78rem" }}
										>
											{method}
										</MenuItem>
									))}
								</Select>
							</FormControl>

							<ToggleButtonGroup
								size="small"
								exclusive
								value={statusFilter}
								onChange={(_event, next) => next && setStatusFilter(next)}
								aria-label="Filter by status"
							>
								<ToggleButton
									value="ALL"
									sx={{ px: 1.5, fontSize: "0.72rem", textTransform: "none" }}
								>
									All
								</ToggleButton>
								<ToggleButton
									value="ACTIVE"
									sx={{ px: 1.5, fontSize: "0.72rem", textTransform: "none" }}
								>
									Active
								</ToggleButton>
								<ToggleButton
									value="INACTIVE"
									sx={{ px: 1.5, fontSize: "0.72rem", textTransform: "none" }}
								>
									Inactive
								</ToggleButton>
							</ToggleButtonGroup>

							<Box sx={{ flex: 1, minWidth: 0 }} />

							<ToggleButtonGroup
								size="small"
								exclusive
								value={view}
								onChange={(_event, next) => next && setView(next)}
								aria-label="Switch view"
							>
								<ToggleButton
									value="table"
									aria-label="Table view"
									sx={{ px: 1.25 }}
								>
									<TableRows sx={{ fontSize: 18 }} />
								</ToggleButton>
								<ToggleButton
									value="cards"
									aria-label="Card view"
									sx={{ px: 1.25 }}
								>
									<GridView sx={{ fontSize: 18 }} />
								</ToggleButton>
							</ToggleButtonGroup>

							<Tooltip title="Refresh registry" arrow>
								<span>
									<IconButton
										onClick={() => refetch()}
										disabled={isFetching}
										aria-label="Refresh registry"
										sx={{
											color: "text.secondary",
											border: "1px solid",
											borderColor: "divider",
										}}
									>
										<Refresh
											sx={{
												fontSize: 19,
												animation: isFetching
													? "registrySpin 0.9s linear infinite"
													: "none",
											}}
										/>
									</IconButton>
								</span>
							</Tooltip>
						</Paper>
					)}

					{}
					{!hasEndpoints ? (
						<EmptyRegistry onCreate={() => navigate("/create-mapping")} />
					) : filtered.length === 0 ? (
						<NoResults onClear={clearFilters} />
					) : (
						<>
							{filtersActive && (
								<Typography
									variant="caption"
									sx={{ color: "text.disabled", fontSize: "0.72rem" }}
								>
									Showing {filtered.length} of {endpoints.length} endpoints
									{methodFilter !== "ALL" ? ` · ${methodFilter}` : ""}
									{statusFilter !== "ALL"
										? ` · ${statusFilter.toLowerCase()}`
										: ""}
								</Typography>
							)}
							<EndpointList
								endpoints={filtered}
								view={view}
								onEdit={(endpoint) => navigate(`/edit-mapping/${endpoint.id}`)}
								onDelete={(endpoint) => setPendingDelete(endpoint)}
								onToggle={handleToggle}
							/>
						</>
					)}
				</Box>
			)}

			{}
			<Dialog
				open={Boolean(pendingDelete)}
				onClose={
					deleteMutation.isPending ? undefined : () => setPendingDelete(null)
				}
				maxWidth="xs"
				fullWidth
			>
				<DialogTitle
					sx={{ display: "flex", alignItems: "center", gap: 1.5, pt: 2.5 }}
				>
					<Box
						sx={{
							width: 40,
							height: 40,
							borderRadius: "12px",
							display: "flex",
							alignItems: "center",
							justifyContent: "center",
							color: "error.main",
							backgroundColor: alpha(
								theme.palette.error.main,
								isDark ? 0.16 : 0.09,
							),
							border: `1px solid ${alpha(theme.palette.error.main, 0.3)}`,
							flexShrink: 0,
						}}
					>
						<DeleteOutline sx={{ fontSize: 20 }} />
					</Box>
					<Box sx={{ minWidth: 0 }}>
						<Typography
							component="span"
							variant="subtitle1"
							sx={{ display: "block", lineHeight: 1.3 }}
						>
							Delete endpoint
						</Typography>
						<Typography
							className="mono-label"
							component="span"
							sx={{
								display: "block",
								color: "text.disabled",
								fontSize: "0.55rem",
							}}
						>
							{pendingDelete?.endpoint_code || "unknown code"}
						</Typography>
					</Box>
				</DialogTitle>
				<DialogContent>
					<Typography variant="body2" sx={{ color: "text.secondary" }}>
						This permanently removes the endpoint and every parameter mapping
						attached to it. Calls routed through it will fail afterwards. This
						cannot be undone.
					</Typography>
				</DialogContent>
				<DialogActions sx={{ px: 3, pb: 2.5 }}>
					<Button
						color="inherit"
						onClick={() => setPendingDelete(null)}
						disabled={deleteMutation.isPending}
					>
						Cancel
					</Button>
					<Button
						color="error"
						variant="contained"
						onClick={confirmDelete}
						disabled={deleteMutation.isPending}
						startIcon={
							deleteMutation.isPending ? (
								<CircularProgress size={16} thickness={5} color="inherit" />
							) : (
								<DeleteOutline sx={{ fontSize: 18 }} />
							)
						}
					>
						{deleteMutation.isPending ? "Deleting…" : "Delete"}
					</Button>
				</DialogActions>
			</Dialog>
		</Box>
	);
}
