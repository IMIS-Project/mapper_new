import { Box, CircularProgress, Container, Typography } from "@mui/material";
import { AnimatePresence } from "framer-motion";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
	Navigate,
	Route,
	Routes,
	useLocation,
	useOutlet,
} from "react-router-dom";
import { PageTransition } from "./components/common/PageTransition";
import Header from "./components/layout/Header";
import Sidebar from "./components/layout/Sidebar";
import { AuthGuard, AuthProvider } from "./context/AuthContext";
import { SnackbarProvider } from "./context/SnackbarContext";
import { ThemeContextProvider } from "./context/ThemeContext";
import LoginPage from "./pages/LoginPage";

const EndpointsPage = lazy(() => import("./pages/EndpointsPage"));
const CreateMappingPage = lazy(() => import("./pages/CreateMappingPage"));
const EditMappingPage = lazy(() => import("./pages/EditMappingPage"));
const GatewayPage = lazy(() => import("./pages/GatewayPage"));
const BankApiPage = lazy(() => import("./pages/BankApiPage"));
const LogsPage = lazy(() => import("./pages/LogsPage"));
const CronJobsPage = lazy(() => import("./pages/CronJobsPage"));
const ExportImportPage = lazy(() => import("./pages/ExportImportPage"));
const WorkflowsPage = lazy(() => import("./pages/WorkflowsPage"));
const WorkflowBuilderPage = lazy(() => import("./pages/WorkflowBuilderPage"));
const EnvVarsPage = lazy(() => import("./pages/EnvVarsPage"));

function RouteLoader() {
	return (
		<Box
			sx={{
				display: "flex",
				flexDirection: "column",
				alignItems: "center",
				justifyContent: "center",
				gap: 2,
				py: 12,
			}}
		>
			<CircularProgress size={28} thickness={4.5} />
			<Typography className="mono-label" sx={{ color: "text.secondary" }}>
				Loading module
			</Typography>
		</Box>
	);
}

function AppLayout() {
	const location = useLocation();
	const outlet = useOutlet();
	const mainRef = useRef(null);
	const [mobileOpen, setMobileOpen] = useState(false);

	useEffect(() => {
		mainRef.current?.scrollTo({ top: 0 });
	}, [location.pathname]);

	return (
		<Box
			sx={{
				display: "flex",
				height: "100vh",
				overflow: "hidden",
				bgcolor: "background.default",
			}}
		>
			<Sidebar
				mobileOpen={mobileOpen}
				onMobileClose={() => setMobileOpen(false)}
			/>

			<Box
				sx={{
					flex: 1,
					minWidth: 0,
					display: "flex",
					flexDirection: "column",
					height: "100vh",
				}}
			>
				<Header onMenuClick={() => setMobileOpen(true)} />

				<Box
					ref={mainRef}
					component="main"
					sx={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}
				>
					<Container
						maxWidth={false}
						sx={{ py: { xs: 2, sm: 3 }, px: { xs: 2, sm: 3, lg: 4 } }}
					>
						<AnimatePresence mode="wait" initial={false}>
							<PageTransition key={location.pathname}>
								<Suspense fallback={<RouteLoader />}>{outlet}</Suspense>
							</PageTransition>
						</AnimatePresence>
					</Container>
				</Box>
			</Box>
		</Box>
	);
}

export default function App() {
	return (
		<ThemeContextProvider>
			<AuthProvider>
				<SnackbarProvider>
					<Routes>
						<Route path="/login" element={<LoginPage />} />

						<Route
							element={
								<AuthGuard>
									<AppLayout />
								</AuthGuard>
							}
						>
							<Route path="/" element={<EndpointsPage />} />
							<Route path="/create-mapping" element={<CreateMappingPage />} />
							<Route path="/edit-mapping/:id" element={<EditMappingPage />} />
							<Route path="/gateway" element={<GatewayPage />} />
						<Route path="/bank-apis" element={<BankApiPage />} />
							<Route path="/logs" element={<LogsPage />} />
							<Route path="/scheduled-jobs" element={<CronJobsPage />} />
							<Route path="/workflows" element={<WorkflowsPage />} />
							<Route path="/workflows/:id" element={<WorkflowBuilderPage />} />
							<Route path="/env-variables" element={<EnvVarsPage />} />
							<Route path="/export-import" element={<ExportImportPage />} />
						</Route>


						<Route path="*" element={<Navigate to="/" replace />} />
					</Routes>
				</SnackbarProvider>
			</AuthProvider>
		</ThemeContextProvider>
	);
}
