import {
	ArrowDownward,
	ArrowForward,
	ArrowUpward,
	CallMade,
	DeleteOutline,
	EditOutlined,
	PowerSettingsNewOutlined,
	Storage,
	UnfoldMore,
} from "@mui/icons-material";
import {
	Box,
	Chip,
	IconButton,
	Paper,
	Table,
	TableBody,
	TableCell,
	TableContainer,
	TableHead,
	TableRow,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useMemo, useState } from "react";

import MethodChip from "../common/MethodChip";
import EndpointCard, { ActiveChip } from "./EndpointCard";

const HEAD_CELL_SX = {
	fontFamily: "var(--font-mono)",
	fontSize: "0.6rem",
	fontWeight: 600,
	letterSpacing: "0.14em",
	textTransform: "uppercase",
	color: "text.secondary",
	py: 1.1,
	whiteSpace: "nowrap",
};

const SORT_KEYS = [
	{ key: "endpoint_code", label: "Code" },
	{ key: "method", label: "Method" },
	{ key: "created_at", label: "Created" },
];

function formatDate(value) {
	if (!value) return "—";
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return "—";
	return date.toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
		year: "numeric",
	});
}

function compareEndpoints(a, b, key) {
	if (key === "created_at") {
		const av = a?.created_at ? new Date(a.created_at).getTime() : 0;
		const bv = b?.created_at ? new Date(b.created_at).getTime() : 0;
		return av - bv;
	}
	const av = String(a?.[key] ?? "").toLowerCase();
	const bv = String(b?.[key] ?? "").toLowerCase();
	return av.localeCompare(bv);
}

function SortHeader({
	label,
	sortKey,
	sort,
	onSortChange,
	align = "left",
	width,
}) {
	const active = sort.key === sortKey;
	const SortIcon = active
		? sort.dir === "asc"
			? ArrowUpward
			: ArrowDownward
		: UnfoldMore;

	return (
		<TableCell align={align} sx={{ ...HEAD_CELL_SX, width }}>
			<Box
				component="button"
				type="button"
				onClick={() => onSortChange(sortKey)}
				aria-label={`Sort by ${label.toLowerCase()}`}
				sx={{
					all: "unset",
					cursor: "pointer",
					display: "inline-flex",
					alignItems: "center",
					gap: 0.5,
					color: active ? "text.primary" : "inherit",
					transition: "color 0.15s ease",
					"&:hover": { color: "text.primary" },
					"&:focus-visible": {
						outline: "2px solid",
						outlineColor: "primary.main",
						borderRadius: "4px",
					},
				}}
			>
				<span
					className="mono-label"
					style={{ fontSize: "0.6rem", letterSpacing: "0.14em" }}
				>
					{label}
				</span>
				<SortIcon sx={{ fontSize: 13, opacity: active ? 1 : 0.35 }} />
			</Box>
		</TableCell>
	);
}

export default function EndpointList({
	endpoints = [],
	view = "table",
	onEdit,
	onDelete,
	onToggle,
	onSftp,
}) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const codeFont = theme.typography.fontFamilyCode;

	const [sort, setSort] = useState({ key: "created_at", dir: "desc" });

	const sorted = useMemo(() => {
		const rows = [...endpoints];
		rows.sort((a, b) => {
			const order = compareEndpoints(a, b, sort.key);
			return sort.dir === "asc" ? order : -order;
		});
		return rows;
	}, [endpoints, sort]);

	const handleSortChange = (key) => {
		setSort((prev) =>
			prev.key === key
				? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
				: { key, dir: key === "created_at" ? "desc" : "asc" },
		);
	};

	const stop = (event) => event.stopPropagation();

	const rowActions = (endpoint) => (
		<Box sx={{ display: "inline-flex", gap: 0.25 }} onClick={stop}>
			<Tooltip title="Edit mapping" arrow>
				<IconButton
					size="small"
					onClick={() => onEdit?.(endpoint)}
					aria-label={`Edit ${endpoint?.endpoint_code || "endpoint"}`}
					sx={{ color: "text.secondary", "&:hover": { color: "primary.main" } }}
				>
					<EditOutlined sx={{ fontSize: 17 }} />
				</IconButton>
			</Tooltip>
			{endpoint?.protocol === "SFTP" || endpoint?.sftp_host ? (
				<Tooltip title="SFTP settings" arrow>
					<IconButton
						size="small"
						onClick={() => onSftp?.(endpoint)}
						aria-label={`SFTP settings for ${endpoint?.endpoint_code || "endpoint"}`}
						sx={{ color: "text.secondary", "&:hover": { color: "primary.main" } }}
					>
						<Storage sx={{ fontSize: 17 }} />
					</IconButton>
				</Tooltip>
			) : null}
			<Tooltip
				title={
					endpoint?.is_active ? "Deactivate endpoint" : "Activate endpoint"
				}
				arrow
			>
				<IconButton
					size="small"
					onClick={() => onToggle?.(endpoint)}
					aria-label={`${endpoint?.is_active ? "Deactivate" : "Activate"} ${endpoint?.endpoint_code || "endpoint"}`}
					sx={{
						color: endpoint?.is_active ? "warning.main" : "success.main",
						opacity: 0.85,
						"&:hover": { opacity: 1 },
					}}
				>
					<PowerSettingsNewOutlined sx={{ fontSize: 17 }} />
				</IconButton>
			</Tooltip>
			<Tooltip title="Delete endpoint" arrow>
				<IconButton
					size="small"
					onClick={() => onDelete?.(endpoint)}
					aria-label={`Delete ${endpoint?.endpoint_code || "endpoint"}`}
					sx={{ color: "text.secondary", "&:hover": { color: "error.main" } }}
				>
					<DeleteOutline sx={{ fontSize: 17 }} />
				</IconButton>
			</Tooltip>
		</Box>
	);

	if (view === "cards") {
		return (
			<Box>
				{}
				<Box
					sx={{
						display: "flex",
						alignItems: "center",
						gap: 1,
						flexWrap: "wrap",
						mb: 1.5,
					}}
				>
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", fontSize: "0.55rem" }}
					>
						Sort
					</Typography>
					{SORT_KEYS.map(({ key, label }) => {
						const active = sort.key === key;
						const Icon = active
							? sort.dir === "asc"
								? ArrowUpward
								: ArrowDownward
							: UnfoldMore;
						return (
							<Chip
								key={key}
								size="small"
								label={label}
								onClick={() => handleSortChange(key)}
								variant={active ? "filled" : "outlined"}
								color={active ? "primary" : "default"}
								icon={<Icon sx={{ fontSize: "13px !important" }} />}
								sx={{
									fontFamily: codeFont,
									fontSize: "0.66rem",
									height: 26,
									color: active ? undefined : "text.secondary",
								}}
							/>
						);
					})}
				</Box>

				<Box
					sx={{
						display: "grid",
						gridTemplateColumns: {
							xs: "1fr",
							sm: "repeat(auto-fill, minmax(330px, 1fr))",
						},
						gap: 2,
					}}
				>
					{sorted.map((endpoint) => (
						<EndpointCard
							key={endpoint.id}
							endpoint={endpoint}
							onEdit={onEdit}
							onDelete={onDelete}
							onToggle={onToggle}
							onSftp={onSftp}
						/>
					))}
				</Box>
			</Box>
		);
	}

	return (
		<TableContainer
			component={Paper}
			elevation={0}
			sx={{
				border: "1px solid",
				borderColor: "divider",
				borderRadius: 3,
				overflow: "hidden",
				backgroundColor: alpha(theme.palette.background.paper, 0.9),
			}}
		>
			<Table size="small" sx={{ minWidth: 900 }}>
				<TableHead>
					<TableRow
						sx={{
							"& th": {
								backgroundColor: alpha(
									theme.palette.background.default,
									isDark ? 0.5 : 0.72,
								),
								borderBottom: "1px solid",
								borderColor: "divider",
							},
						}}
					>
						<SortHeader
							label="Endpoint"
							sortKey="endpoint_code"
							sort={sort}
							onSortChange={handleSortChange}
							width={220}
						/>
						<TableCell sx={HEAD_CELL_SX}>Route</TableCell>
						<SortHeader
							label="Method"
							sortKey="method"
							sort={sort}
							onSortChange={handleSortChange}
							width={110}
						/>
						<TableCell sx={{ ...HEAD_CELL_SX, width: 110 }}>Status</TableCell>
						<SortHeader
							label="Created"
							sortKey="created_at"
							sort={sort}
							onSortChange={handleSortChange}
							width={120}
						/>
						<TableCell align="right" sx={{ ...HEAD_CELL_SX, width: 130 }}>
							Actions
						</TableCell>
					</TableRow>
				</TableHead>

				<TableBody>
					{sorted.map((endpoint) => {
						const code = endpoint?.endpoint_code || "—";
						return (
							<TableRow
								key={endpoint.id}
								hover
								sx={{
									cursor: "pointer",
									"&:last-child td": { borderBottom: 0 },
									"&:hover td": {
										backgroundColor: alpha(
											theme.palette.primary.main,
											isDark ? 0.06 : 0.03,
										),
									},
								}}
							>
								<TableCell
									onClick={() => onEdit?.(endpoint)}
									sx={{ maxWidth: 240 }}
								>
									<Tooltip title={code} arrow>
										<Typography
											sx={{
												fontFamily: codeFont,
												fontSize: "0.78rem",
												fontWeight: 700,
												overflow: "hidden",
												textOverflow: "ellipsis",
												whiteSpace: "nowrap",
											}}
										>
											{code}
										</Typography>
									</Tooltip>
									{endpoint?.description && (
										<Typography
											variant="caption"
											sx={{
												display: "block",
												color: "text.disabled",
												maxWidth: 230,
												overflow: "hidden",
												textOverflow: "ellipsis",
												whiteSpace: "nowrap",
											}}
										>
											{endpoint.description}
										</Typography>
									)}
								</TableCell>

								<TableCell
									onClick={() => onEdit?.(endpoint)}
									sx={{ maxWidth: 360 }}
								>
									<Box
										sx={{
											display: "flex",
											flexDirection: "column",
											gap: 0.35,
											minWidth: 240,
										}}
									>
										<Box
											sx={{
												display: "flex",
												alignItems: "center",
												gap: 0.75,
												minWidth: 0,
											}}
										>
											<CallMade
												sx={{
													fontSize: 13,
													color: "primary.main",
													flexShrink: 0,
												}}
											/>
											<Tooltip title={endpoint?.source_api_url || ""} arrow>
												<Typography
													sx={{
														fontFamily: codeFont,
														fontSize: "0.7rem",
														overflow: "hidden",
														textOverflow: "ellipsis",
														whiteSpace: "nowrap",
													}}
												>
													{endpoint?.source_api_url || "—"}
												</Typography>
											</Tooltip>
										</Box>
										<Box
											sx={{
												display: "flex",
												alignItems: "center",
												gap: 0.75,
												minWidth: 0,
											}}
										>
											<ArrowForward
												sx={{
													fontSize: 13,
													color: "text.disabled",
													flexShrink: 0,
													ml: 0.1,
													transform: "rotate(90deg)",
												}}
											/>
											<Tooltip title={endpoint?.target_api_url || ""} arrow>
												<Typography
													sx={{
														fontFamily: codeFont,
														fontSize: "0.7rem",
														color: "text.secondary",
														overflow: "hidden",
														textOverflow: "ellipsis",
														whiteSpace: "nowrap",
													}}
												>
													{endpoint?.target_api_url || "—"}
												</Typography>
											</Tooltip>
										</Box>
									</Box>
								</TableCell>

								<TableCell onClick={() => onEdit?.(endpoint)}>
									<Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
										<MethodChip method={endpoint?.method} />
										{String(endpoint?.protocol ?? "").toUpperCase() ===
											"SFTP" && (
											<Chip
												size="small"
												label="SFTP"
												variant="outlined"
												sx={{
													height: 20,
													fontFamily: "var(--font-mono)",
													fontSize: "0.58rem",
												}}
											/>
										)}
									</Box>
								</TableCell>

								<TableCell onClick={() => onEdit?.(endpoint)}>
									<ActiveChip active={Boolean(endpoint?.is_active)} />
								</TableCell>

								<TableCell onClick={() => onEdit?.(endpoint)}>
									<Typography
										className="mono-label"
										sx={{ color: "text.secondary", fontSize: "0.6rem" }}
									>
										{formatDate(endpoint?.created_at)}
									</Typography>
								</TableCell>

								<TableCell align="right">{rowActions(endpoint)}</TableCell>
							</TableRow>
						);
					})}
				</TableBody>
			</Table>
		</TableContainer>
	);
}
