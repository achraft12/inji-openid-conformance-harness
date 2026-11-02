-- Runs only in the harness database, after the unchanged upstream schema.
-- Replace the stock LDP/ngrok seed, never production application data.
\connect inji_certify
DELETE FROM certify.credential_config WHERE credential_config_key_id = 'FarmerCredential';

INSERT INTO certify.credential_config (
    credential_config_key_id, config_id, status, vc_template,
    sd_jwt_vct, credential_format, did_url,
    key_manager_app_id, key_manager_ref_id, signature_algo,
    sd_claim, display, display_order, scope,
    cryptographic_binding_methods_supported,
    credential_signing_alg_values_supported, proof_types_supported,
    sd_jwt_claims, cr_dtimes
) VALUES (
    'ConformanceSDJWT', 'conformance-sd-jwt-v1', 'active',
    encode(convert_to('{"fullName":"${fullName}"}', 'UTF8'), 'base64'),
    'https://certify.conformance.test:8443/credentials/conformance',
    'dc+sd-jwt', 'did:web:certify.conformance.test%3A8443',
    'CERTIFY_VC_SIGN_EC_R1', 'EC_SECP256R1_SIGN', 'ES256',
    '$.fullName',
    '[{"name":"Conformance SD-JWT","locale":"en"}]'::jsonb,
    ARRAY['fullName'], 'conformance_sd_jwt',
    ARRAY['jwk'], ARRAY['ES256'],
    '{"jwt":{"proof_signing_alg_values_supported":["ES256"]}}'::jsonb,
    '{"fullName":{"display":[{"name":"Full name","locale":"en"}]}}'::jsonb,
    CURRENT_TIMESTAMP
);
