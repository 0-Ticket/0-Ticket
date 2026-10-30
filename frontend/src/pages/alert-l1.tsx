import { useParams } from 'react-router';
import { useAlertL1 } from '../api/ticket-queries';
import { AgentLog } from '../components/agent-log';
import { Badge, ObjectId, QueryError, StatusNote, Timestamp } from '../components/contract-display';
import { ContractFields, EvidenceList } from '../components/evidence-list';
import { BranchPath, DecisionList, EvidenceRequestList } from '../components/l1-records';
import { Breadcrumbs } from '../components/page-header';
import { Section } from '../components/ui/card';

// F1 detail, L1 result read: the L1 result of one alert, including alerts held before a Ticket
// existed. Read-only; the screen never changes a branch, a decision or a request.
export function AlertL1Page() {
  const { alert_id = '' } = useParams();
  const query = useAlertL1(alert_id);
  const detail = query.data;
  return (
    <div>
      {query.isPending && <StatusNote busy>알럿 L1 결과 불러오는 중…</StatusNote>}
      {query.error && (
        <QueryError
          error={query.error}
          busy={query.isFetching}
          retry={() => void query.refetch()}
        />
      )}
      {detail && (
        <>
          <Breadcrumbs list="L1 결과 조회" to="/review" current={detail.alert.alert_id} />
          <header className="min-w-0 space-y-3 rounded-lg border border-border bg-card p-4 shadow-card">
            <div className="flex flex-wrap items-center gap-2">
              <Badge value={null} severity={detail.alert.severity_id} />
              <span className="rounded bg-inset px-2 py-0.5 text-xs font-semibold">
                중복 합계 {detail.alert.count}건
              </span>
            </div>
            <h1 className="text-xl font-semibold tracking-tight break-all">
              알럿 {detail.alert.alert_id}
            </h1>
            <ObjectId value={detail.alert.alert_id} />
            <p className="break-words text-muted-foreground">{detail.alert.rule_name}</p>
            <div className="grid gap-x-6 gap-y-1 border-t border-border pt-3 text-sm text-muted-foreground lg:grid-cols-2">
              <p>
                발생: <Timestamp value={detail.alert.time} /> · 최초{' '}
                <Timestamp value={detail.alert.first_seen} />
              </p>
              <p>
                최근: <Timestamp value={detail.alert.last_seen} />
              </p>
            </div>
          </header>
          <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]">
            <div className="min-w-0 space-y-4">
              <DecisionList decisions={detail.decisions} description="이 알럿의 승격·보류 기록" />
              <EvidenceRequestList requests={detail.evidence_requests} />
              <AgentLog steps={detail.steps} />
            </div>
            <aside className="min-w-0 space-y-4">
              <BranchPath branch={detail.branch} />
              <Section
                label="알럿 필드와 Lookup"
                description="알럿 원본 필드와 자산·계정 조회 결과"
              >
                <ContractFields value={{ ...detail.alert }} />
                <EvidenceList
                  label={`원본 연결 ${detail.alert.alert_id}`}
                  evidence={detail.alert.raw_ids.map((id) => ({
                    ref_type: 'raw',
                    ref_id: id,
                    note: '원본 로그',
                  }))}
                />
              </Section>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
