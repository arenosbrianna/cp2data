import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { DssProvider } from './dss/context';
import { Shell } from './dss/Shell';
import { LoginPage } from './dss/LoginPage';
import { OverviewPage } from './dss/pages/OverviewPage';
import { ForecastPage } from './dss/pages/ForecastPage';
import { RiskPage } from './dss/pages/RiskPage';
import { PurchasingPage } from './dss/pages/PurchasingPage';
import { TrackingPage } from './dss/pages/TrackingPage';
import { NotFoundPage } from './pages/NotFoundPage';

export const App: React.FC = () => (
  <DssProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<Shell />}>
          <Route index element={<OverviewPage />} />
          <Route path="forecasting" element={<ForecastPage />} />
          <Route path="risk" element={<RiskPage />} />
          <Route path="purchasing" element={<PurchasingPage />} />
          <Route path="tracking" element={<TrackingPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </DssProvider>
);

export default App;
