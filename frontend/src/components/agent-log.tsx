import type { AgentStep } from '../contracts';
import { Timestamp } from './contract-display';

export function AgentLog({ steps }: { steps: AgentStep[] }) {
  const groups = new Map<string, AgentStep[]>();
  for (const step of steps)
    groups.set(step.subject_id, [...(groups.get(step.subject_id) ?? []), step]);
  return (
    <section aria-label="Agent Log" className="space-y-3">
      <h2 className="text-lg font-semibold">Agent Log</h2>
      {!steps.length && <p>없음</p>}
      {[...groups].map(([id, items]) => (
        <div key={id}>
          <h3 className="font-mono">{id}</h3>
          <ol className="space-y-3 border-l border-border pl-4">
            {[...items]
              .sort((a, b) => a.step - b.step)
              .map((step) => (
                <li
                  key={step.step}
                  data-testid="agent-step"
                  data-step={step.step}
                  className="space-y-2 rounded border border-border p-3 text-sm"
                >
                  <p className="font-semibold">
                    단계 {step.step} · {step.agent} · {step.action}
                  </p>
                  <Timestamp value={step.created_at} />
                  <p>
                    도구: {step.tool ?? '없음'} · 모델: {step.model ?? '없음'} · 토큰:{' '}
                    {step.tokens ?? '없음'} · 지연: {step.latency_ms} ms
                  </p>
                  <p>프롬프트 버전: {step.prompt_version ?? '없음'}</p>
                  <details>
                    <summary className="cursor-pointer">입력·출력 발췌</summary>
                    <h4>입력</h4>
                    <pre className="whitespace-pre-wrap break-words">{step.input_excerpt}</pre>
                    <h4>출력</h4>
                    <pre className="whitespace-pre-wrap break-words">{step.output_excerpt}</pre>
                  </details>
                </li>
              ))}
          </ol>
        </div>
      ))}
    </section>
  );
}
