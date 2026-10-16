import type { IncidentMember } from '../contracts';
import { registeredLabel } from '../lib/display';
import { Badge, ObjectId } from './contract-display';

function memberLink(member: IncidentMember) {
  const id = member.member_type === 'ticket' ? member.ticket_id : member.hunt_id;
  if (id === null) return <span>없음</span>;
  const path = member.member_type === 'ticket' ? 'tickets' : 'hunts';
  return <ObjectId value={id} href={`/${path}/${encodeURIComponent(id)}`} />;
}
function Member({ member }: { member: IncidentMember }) {
  const entity = member.matched_entity;
  return (
    <li data-testid="incident-member" className="space-y-1 rounded border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span>{member.member_type === 'ticket' ? '티켓' : '헌팅 결과'}</span>
        {memberLink(member)}
        <Badge value={member.source} />
      </div>
      <p className="text-sm break-words">규칙: {member.rule}</p>
      <p className="text-sm whitespace-pre-wrap break-words">
        묶은 기준: {entity ? `${registeredLabel(entity.type)} ${entity.value}` : '없음'}
      </p>
      {member.excluded && (
        <p className="text-sm whitespace-pre-wrap break-words">
          제외 사유: {member.excluded_reason ?? '없음'}
        </p>
      )}
    </li>
  );
}
// Grouping is decided by Correlation; the screen only splits by the `excluded` flag.
export function IncidentMembers({ members }: { members: IncidentMember[] }) {
  const sections = [
    { label: '묶음 항목', items: members.filter((member) => !member.excluded) },
    { label: '제외된 항목', items: members.filter((member) => member.excluded) },
  ];
  return (
    <div className="grid items-start gap-6 lg:grid-cols-2">
      {sections.map(({ label, items }) => (
        <section key={label} aria-label={label} className="space-y-3">
          <h2 className="text-lg font-semibold">
            {label} ({items.length})
          </h2>
          {items.length ? (
            <ul className="space-y-2">
              {items.map((member, index) => (
                <Member key={index} member={member} />
              ))}
            </ul>
          ) : (
            <p>없음</p>
          )}
        </section>
      ))}
    </div>
  );
}
