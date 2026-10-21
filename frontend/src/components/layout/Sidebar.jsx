import {
	AccountBalance,
	AccountTree,
	Add,
	Api as ApiIcon,
	ChevronLeft,
	Close,
	ImportExport,
	Key,
	ListAlt,
	Logout,
	Send as SendIcon,
	Schedule,
} from "@mui/icons-material";
import {
	Avatar,
	Box,
	Divider,
	Drawer,
	IconButton,
	List,
	ListItemButton,
	ListItemIcon,
	Tooltip,
	Typography,
	useMediaQuery,
} from "@mui/material";
import { alpha, styled, useTheme } from "@mui/material/styles";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../../context/AuthContext";
import { useSnackbar } from "../../context/SnackbarContext";

const EXPANDED_WIDTH = 264;
const COLLAPSED_WIDTH = 76;
const COLLAPSED_STORAGE_KEY = "sidebar-collapsed";

const NAV_ITEMS = [
	{
		label: "Endpoints",
		to: "/",
		icon: <ApiIcon fontSize="small" />,
		end: true,
	},
	{
		label: "Create Mapping",
		to: "/create-mapping",
		icon: <Add fontSize="small" />,
	},
	{
		label: "Gateway Tester",
		to: "/gateway",
		icon: <SendIcon fontSize="small" />,
	},
	{
		label: "Bank APIs",
		to: "/bank-apis",
		icon: <AccountBalance fontSize="small" />,
	},
	{ label: "Call Logs", to: "/logs", icon: <ListAlt fontSize="small" /> },
	{ label: "Cron Jobs", to: "/scheduled-jobs", icon: <Schedule fontSize="small" /> },
	{
		label: "Workflows",
		to: "/workflows",
		icon: <AccountTree fontSize="small" />,
	},
	{
		label: "Env Variables",
		to: "/env-variables",
		icon: <Key fontSize="small" />,
	},
	{
		label: "Export / Import",
		to: "/export-import",
		icon: <ImportExport fontSize="small" />,
	},
];

const StyledDrawer = styled(Drawer, {
	shouldForwardProp: (prop) => prop !== "collapsed",
})(({ theme, collapsed }) => ({
	width: collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH,
	flexShrink: 0,
	whiteSpace: "nowrap",
	"& .MuiDrawer-paper": {
		width: collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH,
		boxSizing: "border-box",
		borderRight: `1px solid ${theme.palette.divider}`,
		backgroundColor: theme.palette.background.paper,
		transition: theme.transitions.create("width", {
			easing: theme.transitions.easing.easeInOut,
			duration: theme.transitions.duration.standard,
		}),
		overflowX: "hidden",
		height: "100vh",
		display: "flex",
		flexDirection: "column",
	},
}));

const SidebarHeader = styled(Box, {
	shouldForwardProp: (prop) => prop !== "collapsed",
})(({ theme, collapsed }) => ({
	display: "flex",
	alignItems: "center",
	justifyContent: collapsed ? "center" : "flex-start",
	padding: collapsed ? "18px 0" : "18px 16px",
	minHeight: 68,
	borderBottom: `1px solid ${theme.palette.divider}`,
	cursor: collapsed !== undefined ? "pointer" : "default",
	transition: "background-color 0.2s ease",
	flexShrink: 0,
	"&:hover": {
		backgroundColor: alpha(theme.palette.primary.main, 0.04),
	},
}));

const LogoMark = styled(Box)(({ theme }) => ({
	width: 38,
	height: 38,
	borderRadius: "11px",
	display: "flex",
	alignItems: "center",
	justifyContent: "center",
	flexShrink: 0,
	background: "linear-gradient(135deg, #1e8d39 0%, #4ecb6d 100%)",
	boxShadow: `0 6px 16px ${alpha(theme.palette.primary.main, 0.35)}`,
}));

const NavItem = styled(ListItemButton, {
	shouldForwardProp: (prop) => prop !== "active" && prop !== "collapsed",
})(({ theme, active, collapsed }) => ({
	position: "relative",
	borderRadius: 10,
	margin: collapsed ? "3px 10px" : "3px 12px",
	padding: collapsed ? "10px 0" : "9px 12px",
	justifyContent: collapsed ? "center" : "flex-start",
	color: active ? theme.palette.primary.main : theme.palette.text.secondary,
	backgroundColor: active
		? alpha(theme.palette.primary.main, 0.1)
		: "transparent",
	transition: "background-color 0.18s ease, color 0.18s ease",
	"&::before": {
		content: '""',
		position: "absolute",
		left: 0,
		top: "50%",
		transform: "translateY(-50%)",
		width: 3,
		height: active ? 20 : 0,
		borderRadius: "0 4px 4px 0",
		background: "linear-gradient(180deg, #1e8d39, #4ecb6d)",
		transition: "height 0.18s ease",
	},
	"&:hover": {
		backgroundColor: active
			? alpha(theme.palette.primary.main, 0.14)
			: alpha(theme.palette.primary.main, 0.06),
		color: active ? theme.palette.primary.main : theme.palette.text.primary,
	},
	"& .MuiListItemIcon-root": {
		color: "inherit",
		minWidth: collapsed ? "auto" : 34,
		justifyContent: "center",
	},
}));

const UserCard = styled(Box)(({ theme }) => ({
	display: "flex",
	alignItems: "center",
	gap: 10,
	padding: "10px 12px",
	margin: "0 10px",
	borderRadius: 12,
	border: `1px solid ${theme.palette.divider}`,
	backgroundColor: alpha(theme.palette.primary.main, 0.03),
}));

const brandAvatarSx = {
	width: 34,
	height: 34,
	fontSize: "0.85rem",
	fontWeight: 700,
	color: "#ffffff",
	background: "linear-gradient(135deg, #1e8d39 0%, #4ecb6d 100%)",
};

export default function Sidebar({ mobileOpen, onMobileClose }) {
	const theme = useTheme();
	const isMobile = useMediaQuery(theme.breakpoints.down("md"));
	const navigate = useNavigate();
	const location = useLocation();
	const { user, logout } = useAuth();
	const { showSnackbar } = useSnackbar();

	const [collapsed, setCollapsed] = useState(
		() => localStorage.getItem(COLLAPSED_STORAGE_KEY) === "true",
	);

	useEffect(() => {
		localStorage.setItem(COLLAPSED_STORAGE_KEY, String(collapsed));
	}, [collapsed]);

	const effectiveCollapsed = isMobile ? false : collapsed;

	const email = typeof user === "string" ? user : user?.email || "";
	const initial = email ? email.charAt(0).toUpperCase() : "U";

	const isItemActive = (item) =>
		item.end
			? location.pathname === item.to
			: location.pathname === item.to ||
				location.pathname.startsWith(`${item.to}/`);

	const handleNavigate = (to) => {
		navigate(to);
		if (isMobile) onMobileClose?.();
	};

	const handleToggle = () => {
		if (!isMobile) setCollapsed((prev) => !prev);
	};

	const handleLogout = async () => {
		if (isMobile) onMobileClose?.();
		await logout();
		showSnackbar("Signed out of the console", "info");
		navigate("/login", { replace: true });
	};

	const content = (
		<>
			<SidebarHeader
				collapsed={isMobile ? undefined : collapsed}
				onClick={handleToggle}
			>
				<LogoMark>
					<ApiIcon sx={{ fontSize: 22, color: "#ffffff" }} />
				</LogoMark>

				<AnimatePresence initial={false}>
					{!effectiveCollapsed && (
						<Box
							key="wordmark"
							component={motion.div}
							initial={{ opacity: 0, x: -8 }}
							animate={{ opacity: 1, x: 0 }}
							exit={{ opacity: 0, x: -8 }}
							transition={{ duration: 0.16, ease: "easeOut" }}
							sx={{ ml: 1.5, minWidth: 0 }}
						>
							<Typography
								sx={{
									fontWeight: 700,
									fontSize: "0.95rem",
									lineHeight: 1.2,
									whiteSpace: "nowrap",
								}}
							>
								API Mapper
							</Typography>
							<Typography
								className="mono-label"
								sx={{ color: "text.secondary", fontSize: "0.55rem" }}
							>
								Integration Console
							</Typography>
						</Box>
					)}
				</AnimatePresence>

				{!effectiveCollapsed && !isMobile && (
					<IconButton
						size="small"
						sx={{ ml: "auto", color: "text.secondary" }}
						aria-label="Collapse sidebar"
					>
						<ChevronLeft fontSize="small" />
					</IconButton>
				)}
				{isMobile && (
					<IconButton
						size="small"
						sx={{ ml: "auto" }}
						onClick={onMobileClose}
						aria-label="Close menu"
					>
						<Close fontSize="small" />
					</IconButton>
				)}
			</SidebarHeader>

			<Box sx={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>
				<AnimatePresence initial={false}>
					{!effectiveCollapsed && (
						<Typography
							key="section-label"
							component={motion.p}
							initial={{ opacity: 0 }}
							animate={{ opacity: 1 }}
							exit={{ opacity: 0 }}
							className="mono-label"
							sx={{
								px: 2.5,
								pt: 2,
								pb: 0.5,
								m: 0,
								color: "text.disabled",
								fontSize: "0.55rem",
							}}
						>
							Workspace
						</Typography>
					)}
				</AnimatePresence>

				<List sx={{ pt: effectiveCollapsed ? 1.25 : 0.5 }}>
					{NAV_ITEMS.map((item) => {
						const active = isItemActive(item);

						const button = (
							<NavItem
								key={item.to}
								active={active}
								collapsed={effectiveCollapsed}
								onClick={() => handleNavigate(item.to)}
							>
								<ListItemIcon>{item.icon}</ListItemIcon>
								<AnimatePresence initial={false}>
									{!effectiveCollapsed && (
										<Box
											key="label"
											component={motion.div}
											initial={{ opacity: 0, x: -6 }}
											animate={{ opacity: 1, x: 0 }}
											exit={{ opacity: 0, x: -6 }}
											transition={{ duration: 0.15, ease: "easeOut" }}
											sx={{ whiteSpace: "nowrap", overflow: "hidden" }}
										>
											<Typography
												sx={{
													fontSize: "0.85rem",
													fontWeight: active ? 600 : 500,
												}}
											>
												{item.label}
											</Typography>
										</Box>
									)}
								</AnimatePresence>
							</NavItem>
						);

						return effectiveCollapsed ? (
							<Tooltip key={item.to} title={item.label} placement="right" arrow>
								{button}
							</Tooltip>
						) : (
							button
						);
					})}
				</List>
			</Box>

			<Box sx={{ flexShrink: 0, pb: 1.5 }}>
				<Divider sx={{ mx: 2, mb: 1.5 }} />

				{effectiveCollapsed ? (
					<Box
						sx={{
							display: "flex",
							flexDirection: "column",
							alignItems: "center",
							gap: 1.25,
						}}
					>
						<Tooltip title={email || "Signed in"} placement="right" arrow>
							<Avatar sx={brandAvatarSx}>{initial}</Avatar>
						</Tooltip>
						<Tooltip title="Sign out" placement="right" arrow>
							<IconButton
								size="small"
								onClick={handleLogout}
								sx={{ color: "text.secondary" }}
								aria-label="Sign out"
							>
								<Logout fontSize="small" />
							</IconButton>
						</Tooltip>
					</Box>
				) : (
					<UserCard>
						<Avatar sx={brandAvatarSx}>{initial}</Avatar>
						<Box sx={{ minWidth: 0, flex: 1 }}>
							<Typography
								sx={{
									fontSize: "0.78rem",
									fontWeight: 600,
									overflow: "hidden",
									textOverflow: "ellipsis",
									whiteSpace: "nowrap",
								}}
							>
								{email || "Signed in"}
							</Typography>
							<Typography
								className="mono-label"
								sx={{ color: "text.disabled", fontSize: "0.52rem" }}
							>
								Active session
							</Typography>
						</Box>
						<Tooltip title="Sign out" arrow>
							<IconButton
								size="small"
								onClick={handleLogout}
								sx={{ color: "text.secondary" }}
								aria-label="Sign out"
							>
								<Logout fontSize="small" />
							</IconButton>
						</Tooltip>
					</UserCard>
				)}
			</Box>
		</>
	);

	if (isMobile) {
		return (
			<Drawer
				variant="temporary"
				open={mobileOpen}
				onClose={onMobileClose}
				ModalProps={{ keepMounted: true }}
				sx={{
					"& .MuiDrawer-paper": {
						width: EXPANDED_WIDTH,
						boxSizing: "border-box",
						borderRight: `1px solid ${theme.palette.divider}`,
						display: "flex",
						flexDirection: "column",
					},
				}}
			>
				{content}
			</Drawer>
		);
	}

	return (
		<StyledDrawer variant="permanent" collapsed={collapsed}>
			{content}
		</StyledDrawer>
	);
}
