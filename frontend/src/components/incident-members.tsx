import type { IncidentMember } from '../contracts';
import { registeredLabel } from '../lib/display';
import { Badge, ObjectId } from './contract-display';
import { Icon } from './icon';
import { Section } from './ui/card';

function memberLink(member: IncidentMember) {
  const id = member.member_type === 'ticket' ? member.ticket_id : member.hunt_id;
  if (id === null) return <span>없음</span>;
  const path = member.member_type === 'ticket' ? 'tickets' : 'hunts';
  return <ObjectId value={id} href={`/${path}/${encodeURIComponent(id)}`} />;
}
function Member({ member }: { member: IncidentMember }) {
  const entity = member.matched_entity;
  return (
    <li
      data-testid="incident-member"
      className="min-w-0 space-y-1.5 border-b border-border px-3 py-2.5 last:border-0"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Badge value={member.source} />
        <span className="text-xs text-muted-foreground">
          {member.member_type === 'ticket' ? '티켓' : '헌팅 결과'}
        </span>
        {memberLink(member)}
      </div>
      <p className="font-mono text-xs break-all text-muted-foreground">규칙: {member.rule}</p>
      <p className="text-sm whitespace-pre-wrap break-words">
        묶은 기준: {entity ? `${registeredLabel(entity.type)} ${entity.value}` : '없음'}
      </p>
      {member.excluded && (
        <p className="text-sm whitespace-pre-wrap break-words text-muted-foreground">
          제외 사유: {member.excluded_reason ?? '없음'}
        </p>
      )}
    </li>
  );
}
// Grouping is decided by Correlation; the screen only splits by the `excluded` flag.
export function IncidentMembers({ members }: { members: IncidentMember[] }) {
  const sections = [
    {
      label: '묶음 항목',
      icon: 'check' as const,
      tone: 'text-success',
      items: members.filter((member) => !member.excluded),
    },
    {
      label: '제외된 항목',
      icon: 'x' as const,
      tone: 'text-muted-foreground',
      items: members.filter((member) => member.excluded),
    },
  ];
  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      {sections.map(({ label, icon, tone, items }) => (
        <Section
          key={label}
          label={label}
          title={
            <span className={`flex items-center gap-2 ${tone}`}>
              <Icon name={icon} />
              <span className="text-foreground">
                {label} ({items.length})
              </span>
            </span>
          }
          bodyClassName="p-0"
        >
          {items.length ? (
            <ul>
              {items.map((member, index) => (
                <Member key={index} member={member} />
              ))}
            </ul>
          ) : (
            <p className="p-4 text-sm text-muted-foreground">없음</p>
          )}
        </Section>
      ))}
    </div>
  );
}
