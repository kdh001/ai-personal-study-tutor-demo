// 텍스트 노드를 사용해 예제와 피드백을 안전하게 화면에 표시한다.
const container = document.querySelector('#concepts');
async function post(path, body) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '요청 실패');
  return value;
}
function element(tag, text, className) {
  const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node;
}
// 서버의 UTC 시각을 브라우저 현지 시각으로 표시한다.
function reviewText(review) {
  if (!review) return '아직 푼 기록이 없습니다.';
  if (review.priority === 'wrong_first') return '복습 상태: 오답 다시 풀기 · 지금';
  const due = new Date(review.due);
  const label = due.getTime() <= Date.now() ? '복습 가능' : '예정';
  return `복습 상태: ${label} · 간격 ${review.interval}일 · ${due.toLocaleString()}`;
}
async function load() {
  const response = await fetch('/api/concepts');
  if (!response.ok) throw new Error('개념을 불러오지 못했습니다.');
  const {concepts} = await response.json();
  container.replaceChildren();
  for (const concept of concepts) {
    const card = element('article', '', 'card');
    card.append(element('h3', concept.title), element('p', concept.note, 'note'), element('p', concept.question, 'question'));
    const form = document.createElement('form');
    const input = document.createElement('input'); input.placeholder = '답 입력'; input.setAttribute('aria-label', concept.title + ' 답'); input.required = true;
    const submit = element('button', '채점'); submit.type = 'submit';
    const tutor = element('button', '모의 튜터'); tutor.type = 'button'; tutor.className = 'secondary';
    const result = element('p', '', 'result'); result.setAttribute('role', 'status');
    const review = element('p', reviewText(concept.review), 'review');
    form.append(input, submit, tutor); card.append(form, result, review); container.append(card);
    form.addEventListener('submit', async event => { event.preventDefault(); submit.disabled = true; try { const r = await post('/api/answer', {id:concept.id, answer:input.value}); result.textContent = `${r.passed ? '정답입니다.' : '다시 풀어보세요.'} 정답: ${r.answer}\n${r.explanation}${r.schedule_changed ? '' : '\n예정일 전 연습이라 복습 간격은 유지됩니다.'}`; review.textContent = reviewText(r); } catch (err) { result.textContent = err.message; } finally { submit.disabled = false; }});
    tutor.addEventListener('click', async () => { try { result.textContent = (await post('/api/tutor', {id:concept.id})).reply; } catch (err) { result.textContent = err.message; }});
  }
}
load().catch(error => { container.textContent = error.message; });
