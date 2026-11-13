import { useId, useState } from "react";
import { flatten } from "./json";

export function JsonViewer({
  value,
  rawText,
}: {
  value: unknown;
  rawText?: string;
}) {
  const [raw, setRaw] = useState(false);
  const id = useId();
  return (
    <div className="json-viewer">
      <div className="json-toggle" role="group" aria-label="JSON 표시 방식">
        <button
          aria-pressed={!raw}
          aria-controls={id}
          onClick={() => setRaw(false)}
        >
          필드 테이블
        </button>
        <button
          aria-pressed={raw}
          aria-controls={id}
          onClick={() => setRaw(true)}
        >
          원본 JSON
        </button>
      </div>
      <div id={id}>
        {raw ? (
          <pre className="json">
            {rawText ??
              (typeof value === "string"
                ? value
                : JSON.stringify(value, null, 2))}
          </pre>
        ) : (
          <div className="field-table">
            <table aria-label="JSON 필드 테이블">
              <thead>
                <tr>
                  <th scope="col">필드</th>
                  <th scope="col">값</th>
                </tr>
              </thead>
              <tbody>
                {flatten(value).map(([key, text], index) => (
                  <tr key={index}>
                    <th scope="row">{key}</th>
                    <td>{text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
