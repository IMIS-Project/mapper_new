import {
	CallMade,
	CallReceived,
	DeleteOutline,
	EditOutlined,
	MoreVert,
	PowerSettingsNewOutlined,
	Storage,
} from "@mui/icons-material";
import {
	Box,
	Card,
	Chip,
	IconButton,
	ListItemIcon,
	ListItemText,
	Menu,
	MenuItem,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { useState } from "react";

import MethodChip from "../common/MethodChip";

export function ActiveChip({ active, size = "small", sx }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const base = active
		? theme.palette.success.main
		: theme.palette.text.disabled;

	return (
		<Chip
			size={size}
			label={
				<span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
					<span
						aria-hidden
						style={{
							width: 6,
							height: 6,
							borderRadius: "50%",
							backgroundColor: "currentColor",
							boxShadow: active
								? `0 0 0 3px ${alpha(base, isDark ? 0.25 : 0.15)}`
								: "none",
						}}
					/>
					{active ? "Active" : "Inactive"}
				</span>
			}
			sx={{
				fontSize: "0.7rem",
				fontWeight: 600,
				height: 23,
				borderRadius: "7px",
				color: active ? base : "text.secondary",
				backgroundColor: alpha(base, isDark ? 0.16 : 0.09),
				border: `1px solid ${alpha(base, isDark ? 0.4 : 0.26)}`,
				"& .MuiChip-label": { px: 1.05 },
				...sx,
			}}
		/>
	);
}

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

export default function EndpointCard({ endpoint, onEdit, onDelete, onToggle, onSftp }) {
	const theme = useTheme();
	const isDark = theme.palette.mode === "dark";
	const codeFont = theme.typography.fontFamilyCode;

	const [menuAnchor, setMenuAnchor] = useState(null);
	const menuOpen = Boolean(menuAnchor);

	const code = endpoint?.endpoint_code || "—";
	const isActive = Boolean(endpoint?.is_active);

	const urlSx = {
		fontFamily: codeFont,
		fontSize: "0.72rem",
		overflow: "hidden",
		textOverflow: "ellipsis",
		whiteSpace: "nowrap",
	};

	const stop = (event) => event.stopPropagation();
	const closeMenu = () => setMenuAnchor(null);

	return (
		<Card
			elevation={0}
			onClick={() => onEdit?.(endpoint)}
			onKeyDown={(event) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					onEdit?.(endpoint);
				}
			}}
			role="button"
			tabIndex={0}
			aria-label={`Open mapping ${code}`}
			sx={{
				position: "relative",
				overflow: "hidden",
				cursor: "pointer",
				borderRadius: 3,
				border: "1px solid",
				borderColor: "divider",
				backgroundColor: alpha(theme.palette.background.paper, 0.9),
				transition:
					"transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease",
				"&::before": {
					content: '""',
					position: "absolute",
					top: 0,
					bottom: 0,
					left: 0,
					width: 3,
					background: "linear-gradient(180deg, #1e8d39 0%, #4ecb6d 100%)",
					opacity: isActive ? 0.5 : 0.15,
					transition: "opacity 0.18s ease",
				},
				"&:hover": {
					transform: "translateY(-2px)",
					borderColor: alpha(theme.palette.primary.main, 0.45),
					boxShadow: isDark
						? "0 16px 36px rgba(0, 0, 0, 0.42)"
						: "0 16px 36px rgba(16, 31, 51, 0.1)",
				},
				"&:hover::before": { opacity: 1 },
				"&:focus-visible": {
					outline: `2px solid ${theme.palette.primary.main}`,
					outlineOffset: 2,
				},
			}}
		>
			<Box sx={{ p: 2, pl: 2.5 }}>
				{}
				<Box
					sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}
				>
					<MethodChip method={endpoint?.method} />
					<Tooltip title={code} arrow>
						<Typography
							sx={{
								fontFamily: codeFont,
								fontSize: "0.82rem",
								fontWeight: 700,
								minWidth: 0,
								overflow: "hidden",
								textOverflow: "ellipsis",
								whiteSpace: "nowrap",
							}}
						>
							{code}
						</Typography>
					</Tooltip>
					<Box sx={{ flex: 1 }} />
					<ActiveChip active={isActive} />
					<Tooltip title="Actions" arrow>
						<IconButton
							size="small"
							onClick={(event) => {
								stop(event);
								setMenuAnchor(event.currentTarget);
							}}
							aria-label={`Actions for ${code}`}
							sx={{ color: "text.secondary", mr: -0.75 }}
						>
							<MoreVert fontSize="small" />
						</IconButton>
					</Tooltip>
				</Box>

				{}
				{endpoint?.description && (
					<Typography
						variant="body2"
						sx={{
							mt: 1,
							color: "text.secondary",
							fontSize: "0.76rem",
							display: "-webkit-box",
							WebkitLineClamp: 2,
							WebkitBoxOrient: "vertical",
							overflow: "hidden",
						}}
					>
						{endpoint.description}
					</Typography>
				)}

				{}
				<Box
					sx={{
						mt: 1.5,
						px: 1.5,
						py: 1.25,
						borderRadius: 2,
						border: "1px solid",
						borderColor: "divider",
						backgroundColor: alpha(
							theme.palette.background.default,
							isDark ? 0.5 : 0.6,
						),
						display: "flex",
						flexDirection: "column",
						gap: 1,
					}}
				>
					<Box
						sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}
					>
						<CallMade
							sx={{ fontSize: 15, color: "primary.main", flexShrink: 0 }}
						/>
						<Tooltip title={endpoint?.source_api_url || ""} arrow>
							<Typography sx={{ ...urlSx, color: "text.primary" }}>
								{endpoint?.source_api_url || "—"}
							</Typography>
						</Tooltip>
					</Box>
					<Box
						sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}
					>
						<CallReceived
							sx={{ fontSize: 15, color: "secondary.main", flexShrink: 0 }}
						/>
						<Tooltip title={endpoint?.target_api_url || ""} arrow>
							<Typography sx={{ ...urlSx, color: "text.secondary" }}>
								{endpoint?.target_api_url || "—"}
							</Typography>
						</Tooltip>
					</Box>
				</Box>

				{}
				<Box sx={{ display: "flex", alignItems: "center", gap: 1, mt: 1.5 }}>
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", fontSize: "0.52rem" }}
					>
						Created {formatDate(endpoint?.created_at)}
					</Typography>
					<Box sx={{ flex: 1 }} />
					{endpoint?.is_hidden && (
						<Typography
							className="mono-label"
							sx={{ color: "text.disabled", fontSize: "0.52rem" }}
						>
							Hidden
						</Typography>
					)}
				</Box>
			</Box>

			<Menu
				anchorEl={menuAnchor}
				open={menuOpen}
				onClose={closeMenu}
				/* The Menu is portalled to document.body, so its clicks land outside the
           card's DOM subtree and never reach the card's own onClick — but the
           React event still bubbles through this component tree, which would
           fire the card's navigate-to-editor handler. Stop it at the menu. */
				onClick={(event) => event.stopPropagation()}
				anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
				transformOrigin={{ vertical: "top", horizontal: "right" }}
				slotProps={{ paper: { sx: { minWidth: 190, borderRadius: 2 } } }}
			>
				<MenuItem
					onClick={() => {
						closeMenu();
						onEdit?.(endpoint);
					}}
					sx={{ fontSize: "0.82rem" }}
				>
					<ListItemIcon>
						<EditOutlined fontSize="small" />
					</ListItemIcon>
					<ListItemText primaryTypographyProps={{ fontSize: "0.82rem" }}>
						Edit mapping
					</ListItemText>
				</MenuItem>
				<MenuItem
					onClick={() => {
						closeMenu();
						onToggle?.(endpoint);
					}}
					sx={{ fontSize: "0.82rem" }}
				>
					<ListItemIcon>
						<PowerSettingsNewOutlined
							fontSize="small"
							sx={{ color: isActive ? "warning.main" : "success.main" }}
						/>
					</ListItemIcon>
					<ListItemText primaryTypographyProps={{ fontSize: "0.82rem" }}>
						{isActive ? "Deactivate" : "Activate"}
					</ListItemText>
				</MenuItem>
				{endpoint?.protocol === "SFTP" || endpoint?.sftp_host ? (
					<MenuItem
						onClick={() => {
							closeMenu();
							onSftp?.(endpoint);
						}}
						sx={{ fontSize: "0.82rem" }}
					>
						<ListItemIcon>
							<Storage fontSize="small" />
						</ListItemIcon>
						<ListItemText primaryTypographyProps={{ fontSize: "0.82rem" }}>
							SFTP settings
						</ListItemText>
					</MenuItem>
				) : null}
				<MenuItem
					onClick={() => {
						closeMenu();
						onDelete?.(endpoint);
					}}
				>
					<ListItemIcon>
						<DeleteOutline fontSize="small" sx={{ color: "error.main" }} />
					</ListItemIcon>
					<ListItemText
						primaryTypographyProps={{
							fontSize: "0.82rem",
							color: "error.main",
						}}
					>
						Delete
					</ListItemText>
				</MenuItem>
			</Menu>
		</Card>
	);
}
