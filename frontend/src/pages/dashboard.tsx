import type { ReactNode } from 'react';
import { isMissingApi } from '../api/client';
import { useCases } from '../api/case-queries';
import { useHunts } from '../api/hunt-queries';
import { useIncidents } from '../api/incident-queries';
import { useRules } from '../api/rule-queries';
import { useTickets, useWaitingCount } from '../api/ticket-queries';
import {
  Badge,
  QueryError,
  ReviewStateBadge,
  StatusNote,
  Timestamp,
} from '../components/contract-display';
import {
  CountTable,
  EntryLink,
  ItemLink,
  ListPanel,
  StaleNote,
  TopList,
} from '../components/dashboard-panel';
import { PageHeader } from '../components/page-header';
import { PlainText } from '../components/plain-text';
import { ToneBadge } from '../components/ui/badge';
import { MetaLabel, Section } from '../components/ui/card';
import { countBy, TOP_ITEMS } from '../lib/dashboard';
import { registeredLabel } from '../lib/display';

const anomaly = (value: string) => (
  <ToneBadge tone={value === 'true' ? 'warning' : 'neutral'}>
    {value === 'true' ? '이상 징후' : '이상 없음'}
  </ToneBadge>
);
const status = (value: string) => <Badge value={value} />;
const raw = (value: string) => <span className="font-mono text-[13px]">{value}</span>;

function Row({ children }: { children: ReactNode }) {
  return (
    <li className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2">{children}</li>
  );
}

// The waiting count always comes from metrics. The loaded ticket page is never counted.
// After a failed metrics refresh an older count is not shown as if it were current.
function WaitingCount() {
  const query = useWaitingCount();
  if (isMissingApi(query.error))
    return <p className="text-sm text-muted-foreground">검토 대기 건수: 지표 없음</p>;
  if (query.error)
    return (
      <p className="text-sm text-muted-foreground">
        검토 대기 건수를 확인할 수 없습니다. 검토 지표 영역에서 다시 시도하세요.
      </p>
    );
  if (query.data)
    return (
      <p className="text-2xl font-semibold tracking-tight">
        검토 대기 {query.data.tickets_awaiting_human}건
      </p>
    );
  return <StatusNote busy>대기 건수 불러오는 중…</StatusNote>;
}

function TicketPanel() {
  const query = useTickets(true);
  return (
    <ListPanel
      label="Ticket 현황"
      noun="검토 대기 티켓"
      empty="검토 대기 티켓이 없습니다."
      query={query}
      actions={
        <>
          <EntryLink to="/review">검토 대기함으로 이동</EntryLink>
          <EntryLink to="/tickets">전체 티켓으로 이동</EntryLink>
        </>
      }
      intro={
        <div>
          <MetaLabel>지금 검토 필요</MetaLabel>
          <WaitingCount />
        </div>
      }
    >
      {(items) => (
        <TopList label="Ticket 상단 항목">
          {items.slice(0, TOP_ITEMS).map((ticket) => (
            <Row key={ticket.ticket_id}>
              <ItemLink to={`/tickets/${encodeURIComponent(ticket.ticket_id)}`}>
                {ticket.ticket_id}
              </ItemLink>
              <Badge value={ticket.status} />
              <span className="min-w-0 text-xs break-all text-muted-foreground">
                {registeredLabel(ticket.handling_type)} · 우선순위 {ticket.priority}
              </span>
            </Row>
          ))}
        </TopList>
      )}
    </ListPanel>
  );
}

function IncidentPanel() {
  return (
    <ListPanel
      label="Incident 현황"
      noun="Incident"
      empty="Incident가 없습니다."
      query={useIncidents()}
      actions={<EntryLink to="/incidents">Incident 목록으로 이동</EntryLink>}
    >
      {(items) => (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <CountTable
              label="Incident 상태별 수"
              rows={countBy(items, (item) => item.status)}
              render={status}
            />
            <CountTable
              label="Incident L2 검토 상태별 수"
              rows={countBy(items, (item) => item.review_state)}
              render={(value) => <ReviewStateBadge value={value} />}
            />
          </div>
          <TopList label="Incident 상단 항목">
            {items.slice(0, TOP_ITEMS).map((incident) => (
              <Row key={incident.incident_id}>
                <ItemLink to={`/incidents/${encodeURIComponent(incident.incident_id)}`}>
                  {incident.incident_id}
                </ItemLink>
                <Badge value={incident.status} />
                <ReviewStateBadge value={incident.review_state} />
                <span className="w-full min-w-0">
                  <PlainText value={incident.title} />
                </span>
              </Row>
            ))}
          </TopList>
        </>
      )}
    </ListPanel>
  );
}

function CasePanel() {
  return (
    <ListPanel
      label="Case 현황"
      noun="Case"
      empty="Case가 없습니다."
      query={useCases()}
      actions={<EntryLink to="/cases">Case 목록으로 이동</EntryLink>}
    >
      {(items) => (
        <>
          <CountTable
            label="Case 상태별 수"
            rows={countBy(items, (item) => item.status)}
            render={status}
          />
          <TopList label="Case 상단 항목">
            {items.slice(0, TOP_ITEMS).map((item) => (
              <Row key={item.case_id}>
                <ItemLink to={`/cases/${encodeURIComponent(item.case_id)}`}>
                  {item.case_id}
                </ItemLink>
                <Badge value={item.status} />
                <span className="w-full min-w-0">
                  <PlainText value={item.title} />
                </span>
              </Row>
            ))}
          </TopList>
        </>
      )}
    </ListPanel>
  );
}

function HuntPanel() {
  return (
    <ListPanel
      label="헌팅 현황"
      noun="헌팅 결과"
      empty="헌팅 결과가 없습니다."
      query={useHunts()}
      actions={<EntryLink to="/hunts">헌팅 결과로 이동</EntryLink>}
    >
      {(items) => (
        <>
          <CountTable
            label="헌팅 결과 이상 징후별 수"
            rows={countBy(items, (item) => String(item.is_anomaly))}
            render={anomaly}
          />
          <TopList label="헌팅 결과 상단 항목">
            {items.slice(0, TOP_ITEMS).map((hunt) => (
              <Row key={hunt.hunt_id}>
                <ItemLink to={`/hunts/${encodeURIComponent(hunt.hunt_id)}`}>
                  {hunt.hunt_id}
                </ItemLink>
                {anomaly(String(hunt.is_anomaly))}
                <Badge value={null} severity={hunt.severity_id} />
                <span className="w-full min-w-0">
                  <PlainText value={hunt.hypothesis} />
                </span>
              </Row>
            ))}
          </TopList>
        </>
      )}
    </ListPanel>
  );
}

function RulePanel() {
  return (
    <ListPanel
      label="룰 제안 현황"
      noun="룰 제안"
      empty="룰 제안이 없습니다."
      query={useRules()}
      actions={<EntryLink to="/rules">룰 제안으로 이동</EntryLink>}
    >
      {(items) => (
        <>
          <CountTable
            label="룰 제안 상태별 수"
            rows={countBy(items, (item) => item.status)}
            render={status}
          />
          <TopList label="룰 제안 상단 항목">
            {items.slice(0, TOP_ITEMS).map((rule) => (
              <Row key={rule.proposal_id}>
                <ItemLink to={`/rules/${encodeURIComponent(rule.proposal_id)}`}>
                  {rule.proposal_id}
                </ItemLink>
                <Badge value={rule.status} />
                <span className="w-full min-w-0">
                  <PlainText value={rule.title} />
                </span>
              </Row>
            ))}
          </TopList>
        </>
      )}
    </ListPanel>
  );
}

// Metrics are shown exactly as the API returns them. No ratio or score is computed here.
// A missing metrics route (404) only says "지표 없음". A real failure says the same and
// keeps its reason and retry; older values stay only with the stale note.
function MetricsPanel() {
  const query = useWaitingCount();
  const missing = isMissingApi(query.error);
  const failed = query.error && !missing;
  const data = missing ? undefined : query.data;
  return (
    <Section label="검토 지표" className="md:col-span-2">
      {query.isPending && <StatusNote busy>지표 불러오는 중…</StatusNote>}
      {query.error && !data && <StatusNote>지표 없음</StatusNote>}
      {failed && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {data && (
        <>
          {failed && <StaleNote />}
          <p className="text-xs text-muted-foreground">
            집계 기간: <Timestamp value={data.from} /> ~ <Timestamp value={data.to} />. 현재 검토
            대기 건수는 기간과 관계없이 지금 값입니다.
          </p>
          <ul className="grid gap-2 text-sm font-medium sm:grid-cols-3">
            <li className="rounded-md border border-border bg-inset px-3 py-2">
              기간 안 티켓 {data.tickets_total}건
            </li>
            <li className="rounded-md border border-border bg-inset px-3 py-2">
              L1 검토 {data.l1_reviews_total}건 / 뒤집음 {data.l1_overturned}건
            </li>
            <li className="rounded-md border border-border bg-inset px-3 py-2">
              L2 검토 {data.l2_reviews_total}건
            </li>
          </ul>
          <div className="grid gap-4 md:grid-cols-3">
            <CountTable
              label="L2 반려 유형별 수"
              rows={Object.entries(data.l2_rejects_by_type)}
              render={status}
            />
            <CountTable
              label="Incident 묶음 항목 출처별 수"
              rows={Object.entries(data.incident_members_by_source)}
              render={status}
            />
            <CountTable
              label="정규화 실패 사유별 수"
              rows={Object.entries(data.normalize_failures_by_reason)}
              render={raw}
            />
          </div>
        </>
      )}
    </Section>
  );
}

export function DashboardPage() {
  return (
    <div>
      <PageHeader
        eyebrow="SOC OVERVIEW"
        title="운영 대시보드"
        description={
          <p>
            각 업무 목록과 지표 API가 준 값을 그대로 요약합니다. 목록 영역의 개수는 불러온 첫 페이지
            기준이며, 항목은 API 순서대로 보여 줍니다.
          </p>
        }
      />
      <div className="grid min-w-0 gap-4 md:grid-cols-2">
        <TicketPanel />
        <IncidentPanel />
        <CasePanel />
        <HuntPanel />
        <RulePanel />
        <MetricsPanel />
      </div>
    </div>
  );
}
