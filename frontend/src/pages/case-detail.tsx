import { useParams } from 'react-router';
import { useCase } from '../api/case-queries';
import { useIncident } from '../api/incident-queries';
import { CaseTasks } from '../components/case-tasks';
import {
  Badge,
  Extensions,
  ObjectId,
  QueryError,
  ReviewStateBadge,
  StatusNote,
  Timestamp,
} from '../components/contract-display';
import { IncidentReport } from '../components/incident-report';
import { Breadcrumbs } from '../components/page-header';
import { PlainText } from '../components/plain-text';
import { Section } from '../components/ui/card';
import { badges, toneRails } from '../lib/display';
import { cn } from '../lib/utils';

// C11 is not part of the Case detail response. It is read from the existing Incident detail
// Query (same key as F3) only here, and shown as received, never copied into Case data.
function RelatedIncident({ id }: { id: string }) {
  const query = useIncident(id);
  const incident = query.data?.incident;
  return (
    <>
      <Section label="관련 Incident" description="이 Case를 만든 Incident">
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <ObjectId value={id} href={`/incidents/${encodeURIComponent(id)}`} />
          {incident && (
            <>
              <Badge value={incident.status} />
              <ReviewStateBadge value={incident.review_state} />
            </>
          )}
        </p>
        {incident && <p className="text-sm whitespace-pre-wrap break-words">{incident.title}</p>}
        {query.isPending && <StatusNote busy>Incident 불러오는 중…</StatusNote>}
        {query.error && (
          <QueryError
            error={query.error}
            busy={query.isFetching}
            retry={() => void query.refetch()}
          />
        )}
      </Section>
      {query.data && <IncidentReport artifact={query.data.artifact} />}
    </>
  );
}

export function CaseDetailPage() {
  const { case_id = '' } = useParams();
  const query = useCase(case_id);
  const detail = query.data;
  const item = detail?.case;
  const tone = item && Object.hasOwn(badges, item.status) ? badges[item.status].tone : 'neutral';
  return (
    <div>
      {query.isPending && <StatusNote busy>Case 상세 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {detail && item && (
        <>
          <Breadcrumbs list="Case 목록" to="/cases" current={item.case_id} />
          <header
            className={cn(
              'min-w-0 space-y-3 rounded-lg border border-l-4 border-border bg-card p-4 shadow-card',
              toneRails[tone],
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge value={item.status} />
            </div>
            <h1 className="text-xl font-semibold tracking-tight break-all">Case {item.case_id}</h1>
            <ObjectId value={item.case_id} />
            <p className="text-lg font-medium whitespace-pre-wrap break-words">{item.title}</p>
            <div className="grid gap-x-6 gap-y-1 border-t border-border pt-3 text-sm text-muted-foreground lg:grid-cols-3">
              <p className="flex flex-wrap items-center gap-2">
                Incident:{' '}
                <ObjectId
                  value={item.incident_id}
                  href={`/incidents/${encodeURIComponent(item.incident_id)}`}
                />
              </p>
              <p>
                생성: <Timestamp value={item.created_at} />
              </p>
              <p>
                {item.closed_at === null ? (
                  '종결: 없음'
                ) : (
                  <>
                    종결: <Timestamp value={item.closed_at} />
                  </>
                )}
              </p>
            </div>
            <Extensions value={item.extensions} />
          </header>
          <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,400px)]">
            <div className="min-w-0 space-y-4">
              <CaseTasks
                key={item.case_id}
                caseId={item.case_id}
                tasks={item.tasks}
                refreshFailed={query.isError}
              />
              <RelatedIncident id={item.incident_id} />
            </div>
            <aside className="min-w-0 space-y-4">
              <Section label="교훈" description="Case 종결 시 작성">
                <p className="text-sm">
                  <PlainText value={item.lessons} />
                </p>
              </Section>
              <Section label="룰 제안" description="이 Case에서 나온 탐지 룰 제안">
                {detail.proposal_ids.length ? (
                  <ul className="space-y-1">
                    {detail.proposal_ids.map((id) => (
                      <li key={id}>
                        <ObjectId value={id} href={`/rules/${encodeURIComponent(id)}`} />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">없음</p>
                )}
              </Section>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
