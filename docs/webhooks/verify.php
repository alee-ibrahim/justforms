<?php
// Reference verifier for JustForms webhooks (PHP 7.4+).
//
//   $ok = justforms_verify($secret, getallheaders(), file_get_contents('php://input'));
//
// Reject the request when $ok is false. Use the raw body, not re-encoded JSON.

function justforms_verify(string $secret, array $headers, string $body, ?int $now = null, int $tolerance = 300): bool
{
    $lower = array_change_key_case($headers, CASE_LOWER);
    $id = $lower['justforms-webhook-id'] ?? '';
    $timestamp = $lower['justforms-webhook-timestamp'] ?? '';
    if ($id === '' || !ctype_digit($timestamp)) {
        return false;
    }
    if (abs(($now ?? time()) - (int) $timestamp) > $tolerance) {
        return false; // possible replay
    }
    $expected = hash_hmac('sha256', $id . '.' . $timestamp . '.' . $body, $secret);
    // During a secret rotation the header carries two signatures: "v1=...,v1=...".
    foreach (explode(',', $lower['justforms-webhook-signature'] ?? '') as $part) {
        [$version, $value] = array_pad(explode('=', trim($part), 2), 2, '');
        if ($version === 'v1' && hash_equals($expected, $value)) {
            return true;
        }
    }
    return false;
}
