import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';
import { Providers } from './app/providers';
import { routes } from './app/router';
import { config } from './config';
import { startMocks } from './mocks/start';
import './styles.css';

const root = createRoot(document.getElementById('root')!);
startMocks(config)
  .then(() => {
    root.render(
      <StrictMode>
        <Providers>
          <RouterProvider router={createBrowserRouter(routes)} />
        </Providers>
      </StrictMode>,
    );
  })
  .catch(() => {
    root.render(<p role="alert">앱을 시작하지 못했습니다. 설정을 확인하고 새로고침해 주세요.</p>);
  });
