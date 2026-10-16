import type { AgentStep } from '../contracts';
import { Timestamp } from './contract-display';
import { Section } from './ui/card';

// Excerpts are LLM or log text: shown in a monospace block as plain text, never parsed.
const excerpt =
  'max-h-80 overflow-auto rounded-md border border-[#26323d] bg-[#0a0f14] p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-[#c1cbd6] [overflow-wrap:anywhere]';

export function AgentLog({ steps }: { steps: AgentStep[] }) {
  const groups = new Map<string, AgentStep[]>();
  for (const step of steps)
    groups.set(step.subject_id, [...(groups.get(step.subject_id) ?? []), step]);
  return (
    <Section label="Agent Log" description="에이전트가 조회하고 판단한 단계">
      {!steps.length && <p className="text-sm text-muted-foreground">없음</p>}
      {[...groups].map(([id, items]) => (
        <div key={id} className="min-w-0">
          <h3 className="mb-2 font-mono text-xs font-semibold break-all text-muted-foreground">
            {id}
          </h3>
          <ol className="relative space-y-3 before:absolute before:top-2 before:bottom-2 before:left-[5px] before:w-px before:bg-border">
            {[...items]
              .sort((a, b) => a.step - b.step)
              .map((step) => (
                <li
                  key={step.step}
                  data-testid="agent-step"
                  data-step={step.step}
                  className="relative min-w-0 pl-6 text-sm"
                >
                  <span
                    aria-hidden="true"
                    className="absolute top-3.5 left-0 size-[11px] rounded-full border-2 border-card bg-primary shadow-[0_0_0_1px_var(--border-strong)]"
                  />
                  <div className="min-w-0 space-y-1.5 rounded-md border border-border bg-muted p-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                      <p className="min-w-0 font-semibold break-words">
                        단계 {step.step} · {step.agent} · {step.action}
                      </p>
                      <span className="text-xs text-faint-foreground">
                        <Timestamp value={step.created_at} />
                      </span>
                    </div>
                    <p className="font-mono text-xs break-words text-muted-foreground">
                      도구: {step.tool ?? '없음'} · 모델: {step.model ?? '없음'} · 토큰:{' '}
                      {step.tokens ?? '없음'} · 지연: {step.latency_ms} ms
                    </p>
                    <p className="text-xs break-words text-muted-foreground">
                      프롬프트 버전: {step.prompt_version ?? '없음'}
                    </p>
                    <details className="min-w-0">
                      <summary className="cursor-pointer text-xs font-medium text-primary select-none">
                        입력·출력 발췌
                      </summary>
                      <div className="mt-2 grid min-w-0 gap-2 xl:grid-cols-2">
                        <div className="min-w-0">
                          <h4 className="mb-1 text-[11px] font-semibold tracking-wider text-faint-foreground uppercase">
                            입력
                          </h4>
                          <pre className={excerpt}>{step.input_excerpt}</pre>
                        </div>
                        <div className="min-w-0">
                          <h4 className="mb-1 text-[11px] font-semibold tracking-wider text-faint-foreground uppercase">
                            출력
                          </h4>
                          <pre className={excerpt}>{step.output_excerpt}</pre>
                        </div>
                      </div>
                    </details>
                  </div>
                </li>
              ))}
          </ol>
        </div>
      ))}
    </Section>
  );
}
