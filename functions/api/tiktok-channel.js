const TIKWM_API = 'https://www.tikwm.com/api/user/posts';

export async function onRequestGet({ request }) {
  const url = new URL(request.url);
  const unique_id = url.searchParams.get('unique_id') || '';
  const cursor = url.searchParams.get('cursor') || '0';
  const count = url.searchParams.get('count') || '30';

  if (!unique_id) {
    return new Response(JSON.stringify({ error: 'missing_unique_id' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  try {
    const tikwmRes = await fetch(
      `${TIKWM_API}?unique_id=${encodeURIComponent(unique_id)}&count=${count}&cursor=${cursor}`,
      {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          Accept: 'application/json'
        }
      }
    );

    if (!tikwmRes.ok) {
      return new Response(JSON.stringify({ error: 'tikwm_http_error', status: tikwmRes.status }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const data = await tikwmRes.json();
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store',
        'Access-Control-Allow-Origin': '*'
      }
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'fetch_failed', message: e.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
