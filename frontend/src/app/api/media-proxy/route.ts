import { NextRequest } from 'next/server'

import { isAllowedMediaOrigin, rewriteMediaUrlForServer } from '@/lib/media-proxy'

const FORWARDED_RESPONSE_HEADERS = [
  'accept-ranges',
  'cache-control',
  'content-length',
  'content-range',
  'content-type',
  'etag',
  'last-modified',
] as const

export async function GET(request: NextRequest) {
  const targetUrl = String(request.nextUrl.searchParams.get('url') || '').trim()
  if (!targetUrl || !isAllowedMediaOrigin(targetUrl)) {
    return new Response('Invalid media url', { status: 400 })
  }

  const upstreamHeaders = new Headers()
  const range = request.headers.get('range')
  if (range) upstreamHeaders.set('range', range)

  const upstreamResponse = await fetch(rewriteMediaUrlForServer(targetUrl), {
    method: 'GET',
    headers: upstreamHeaders,
    cache: 'no-store',
  })

  if (!upstreamResponse.ok && upstreamResponse.status !== 206) {
    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers: upstreamResponse.headers,
    })
  }

  const responseHeaders = new Headers()
  FORWARDED_RESPONSE_HEADERS.forEach((header) => {
    const value = upstreamResponse.headers.get(header)
    if (value) {
      responseHeaders.set(header, value)
    }
  })

  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    headers: responseHeaders,
  })
}

export async function HEAD(request: NextRequest) {
  const targetUrl = String(request.nextUrl.searchParams.get('url') || '').trim()
  if (!targetUrl || !isAllowedMediaOrigin(targetUrl)) {
    return new Response(null, { status: 400 })
  }

  const upstreamResponse = await fetch(rewriteMediaUrlForServer(targetUrl), {
    method: 'HEAD',
    cache: 'no-store',
  })

  const responseHeaders = new Headers()
  FORWARDED_RESPONSE_HEADERS.forEach((header) => {
    const value = upstreamResponse.headers.get(header)
    if (value) {
      responseHeaders.set(header, value)
    }
  })

  return new Response(null, {
    status: upstreamResponse.status,
    headers: responseHeaders,
  })
}
