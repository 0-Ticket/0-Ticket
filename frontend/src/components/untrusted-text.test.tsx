import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import sample from '../../../tests/fixtures/frontend/untrusted-text.json';
import { PlainText } from './plain-text';

it('renders raw logs, LLM output and extensions only as text', () => {
  const values = [
    sample.payload,
    sample.summary,
    sample.input_excerpt,
    sample.output_excerpt,
    sample.extensions['example.note'],
  ];
  const { container } = render(
    <>
      {values.map((value) => (
        <PlainText key={value} value={value} />
      ))}
    </>,
  );
  for (const value of values) expect(screen.getByText(value)).toBeInTheDocument();
  expect(container.querySelector('script, img, iframe, a')).toBeNull();
});
