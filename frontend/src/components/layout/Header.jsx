import {
	Brightness4,
	Brightness7,
	Menu as MenuIcon,
} from "@mui/icons-material";
import {
	AppBar,
	Box,
	IconButton,
	Toolbar,
	Tooltip,
	Typography,
} from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { motion } from "framer-motion";
import { useLocation } from "react-router-dom";
import { useAppTheme } from "../../context/ThemeContext";

const PAGE_TITLES = {
	"/": "Endpoints",
	"/create-mapping": "Create Mapping",
	"/gateway": "Gateway Tester",
	"/logs": "Call Logs",
	"/scheduled-jobs": "Cron Jobs",
	"/export-import": "Export / Import",
};

const resolveTitle = (pathname) => {
	if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname];
	if (pathname.startsWith("/edit-mapping")) return "Edit Mapping";
	return "API Mapper";
};

export default function Header({ onMenuClick }) {
	const theme = useTheme();
	const { mode, toggleMode } = useAppTheme();
	const location = useLocation();
	const title = resolveTitle(location.pathname);

	return (
		<AppBar
			position="sticky"
			elevation={0}
			sx={{
				bgcolor: alpha(theme.palette.background.paper, 0.86),
				backdropFilter: "blur(12px)",
				color: "text.primary",
				borderBottom: "1px solid",
				borderColor: "divider",
			}}
		>
			<Toolbar
				sx={{ gap: 1.5, minHeight: { xs: 58, sm: 66 }, px: { xs: 2, sm: 3 } }}
			>
				<IconButton
					edge="start"
					onClick={onMenuClick}
					sx={{ display: { md: "none" }, color: "text.secondary" }}
					aria-label="Open navigation"
				>
					<MenuIcon />
				</IconButton>

				<Box sx={{ minWidth: 0 }}>
					<Typography
						className="mono-label"
						sx={{ color: "text.disabled", fontSize: "0.55rem" }}
					>
						API Mapper
					</Typography>
					<Typography
						variant="subtitle1"
						sx={{
							fontWeight: 600,
							lineHeight: 1.2,
							whiteSpace: "nowrap",
							overflow: "hidden",
							textOverflow: "ellipsis",
						}}
					>
						{title}
					</Typography>
				</Box>

				<Box sx={{ flexGrow: 1 }} />

				<Tooltip
					title={
						mode === "dark" ? "Switch to light mode" : "Switch to dark mode"
					}
					arrow
				>
					<IconButton
						onClick={toggleMode}
						sx={{
							color: "text.secondary",
							border: "1px solid",
							borderColor: "divider",
							borderRadius: 2.5,
						}}
						aria-label="Toggle color mode"
					>
						<motion.span
							key={mode}
							initial={{ rotate: -50, opacity: 0.4, scale: 0.85 }}
							animate={{ rotate: 0, opacity: 1, scale: 1 }}
							transition={{ duration: 0.28, ease: "easeOut" }}
							style={{ display: "inline-flex" }}
						>
							{mode === "dark" ? (
								<Brightness7 fontSize="small" />
							) : (
								<Brightness4 fontSize="small" />
							)}
						</motion.span>
					</IconButton>
				</Tooltip>
			</Toolbar>
		</AppBar>
	);
}
