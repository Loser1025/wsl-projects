import {
	env,
	createExecutionContext,
	waitOnExecutionContext,
} from "cloudflare:test";
import { describe, it, expect } from "vitest";
import worker from "../src/index.ts";

async function seedDialer() {
	await env.PHONE_STORE.put('queue', JSON.stringify([
		'zoomphonecall://+812233445555',
		'zoomphonecall://+813344556666'
	]));
	await env.PHONE_STORE.put('current_index', '0');
	await env.PHONE_STORE.put('next_phone', '+812233445555');
	await env.PHONE_STORE.put('system_status', 'running');
	await env.PHONE_STORE.put('results', '[]');
	await env.PHONE_STORE.delete('last_event');
	await env.PHONE_STORE.delete('last_result');
	await env.PHONE_STORE.delete('last_event_time');
	await env.PHONE_STORE.delete('call_phase');
	await env.PHONE_STORE.delete('last_event_info');
}

describe("Zoom dialer worker", () => {
	it("stores the latest call-ended event in KV and returns it from /next", async () => {
		await seedDialer();

		const ctx = createExecutionContext();
		const webhookResponse = await worker.fetch(new Request('http://example.com/webhook', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				event: 'phone.call_ended',
				payload: {
					object: {
						callee_number_number: '+812233445555',
						duration: 12
					}
				}
			})
		}), env, ctx);
		await waitOnExecutionContext(ctx);

		expect(webhookResponse.status).toBe(200);
		expect(await webhookResponse.json()).toMatchObject({
			ok: true,
			nextIndex: 1,
			queueLen: 2,
			nextPhone: '+813344556666'
		});

		const nextResponse = await worker.fetch(new Request('http://example.com/next'), env);
		const data = await nextResponse.json();

		expect(nextResponse.status).toBe(200);
		expect(data).toMatchObject({
			done: false,
			phone: '+813344556666',
			zoomphonecall_url: 'zoomphonecall://+813344556666',
			index: 1,
			total: 2,
			system_status: 'running',
			last_event: 'phone.call_ended',
			last_result: 'コネクト',
			call_phase: 'ended'
		});
		expect(data.last_event_time).toEqual(expect.any(String));
	});

	it("renders the dashboard with client-side screen state management", async () => {
		await seedDialer();

		const response = await worker.fetch(new Request('http://example.com/'), env);
		const html = await response.text();

		expect(response.status).toBe(200);
		expect(response.headers.get('Content-Type')).toContain('text/html');
		expect(html).toContain('id="screen-root"');
		expect(html).toContain('handleCallClick');
		expect(html).toContain('renderScreen');
		expect(html).toContain('zoomphonecall://+812233445555');
	});
});
