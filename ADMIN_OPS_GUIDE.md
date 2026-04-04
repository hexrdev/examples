# Hexr Cloud — Admin Operations Guide

> **For:** Hexr admin  
> **Date:** April 3, 2026  
> **API:** `api.hexr.cloud` | **Admin Key:** stored in 1Password  
> **Cluster:** `gke_hexr-cloud-prod_us-central1-a_hexr-cloud`

---

## Quick Reference

```bash
# Set admin key (store in env, never commit)
export HEXR_ADMIN_KEY="hxr_live_<your-admin-key>"
alias hexr-api='curl -s -H "Authorization: Bearer $HEXR_ADMIN_KEY"'
```

---

## 1. Invite Code Management

### List All Invite Codes

```bash
hexr-api https://api.hexr.cloud/v1/admin/invite-codes | python3 -m json.tool
```

### Create Invite Code

```bash
curl -s -X POST \
  -H "Authorization: Bearer $HEXR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "HEXR-VOLUNTEER-2026",
    "plan": "trial",
    "credits": 100,
    "max_uses": 20
  }' \
  https://api.hexr.cloud/v1/admin/invite-codes | python3 -m json.tool
```

**Plans & Credits:**

| Plan | Credits (HCU) | Pod Limit | CPU | Memory | Best For |
|------|---------------|-----------|-----|--------|----------|
| `trial` | 100 | 3 | 2 cores | 4Gi | Volunteers, hackathons |
| `team` | 2,000 | 20 | 8 cores | 16Gi | Small teams |
| `partner_trial` | 5,000 | 10 | 8 cores | 16Gi | Accelerator partners |
| `enterprise` | Unlimited | 100 | 32 cores | 64Gi | Production |

### Revoke Invite Code

```bash
curl -s -X DELETE \
  -H "Authorization: Bearer $HEXR_ADMIN_KEY" \
  https://api.hexr.cloud/v1/admin/invite-codes/HEXR-VOLUNTEER-2026
```

---

## 2. Volunteer Onboarding Flow (What Happens Automatically)

When a volunteer uses an invite code, the system does ALL of this:

```
Volunteer POSTs /v1/tenants/onboard with invite_code
  │
  ├─ 1. Validates invite code (active, not exhausted, not expired)
  ├─ 2. Creates Tenant record in Cloud SQL
  │     ├── ID: tnt_{random_hex}
  │     ├── Namespace: tenant-{sanitized_name}
  │     ├── Plan: trial (from invite code)
  │     └── Status: active
  │
  ├─ 3. Grants HCU Credits (100 for trial)
  │
  ├─ 4. Generates API Key
  │     ├── Format: hxr_live_{64_hex_chars}
  │     └── Returned ONCE — volunteer must save it
  │
  ├─ 5. Creates K8s Namespace
  │     ├── Name: tenant-{name}
  │     ├── Labels: hexr.dev/managed=true, hexr.dev/tenant-id, hexr.dev/plan
  │     ├── NetworkPolicy: hexr-tenant-default (isolation)
  │     └── ResourceQuota: hexr-tenant-quota (3 pods, 2 CPU, 4Gi)
  │
  └─ 6. Returns quickstart instructions
```

**You (admin) don't need to do anything** — invite codes are self-service.

---

## 3. Monitoring Volunteers

### List All Tenants

```bash
kubectl port-forward -n hexr-system svc/hexr-cloud-api 8080:8080 &
curl -s -H "X-Internal-Token: $(kubectl get secret hexr-cloud-api-internal-token -n hexr-system -o jsonpath='{.data.token}' | base64 -d)" \
  http://localhost:8080/v1/tenants | python3 -m json.tool
```

### Check a Specific Volunteer's Namespace

```bash
# List their pods
kubectl get pods -n tenant-{name}

# Check resource usage
kubectl describe resourcequota hexr-tenant-quota -n tenant-{name}

# Check network policies
kubectl get networkpolicy -n tenant-{name}
```

### Monitor Credit Usage

```bash
hexr-api "https://api.hexr.cloud/v1/admin/tenants/{tenant_id}/metering-audit?window=24h" | python3 -m json.tool
```

### Check All Tenant Namespaces

```bash
kubectl get namespaces -l hexr.dev/managed=true
```

---

## 4. Waitlist Flow (Alternative to Invite Codes)

If you prefer manual approval instead of invite codes:

### Review Pending Signups

```bash
hexr-api https://api.hexr.cloud/v1/admin/waitlist | python3 -m json.tool
```

### Approve a Waitlist Entry

```bash
curl -s -X POST \
  -H "Authorization: Bearer $HEXR_ADMIN_KEY" \
  https://api.hexr.cloud/v1/admin/waitlist/{entry_id}/approve | python3 -m json.tool
```

This automatically creates the tenant + namespace + API key (same as invite code flow).

### Reject a Waitlist Entry

```bash
curl -s -X POST \
  -H "Authorization: Bearer $HEXR_ADMIN_KEY" \
  https://api.hexr.cloud/v1/admin/waitlist/{entry_id}/reject
```

---

## 5. Emergency Operations

### Disable a Volunteer's Tenant

```bash
hexr-api https://api.hexr.cloud/v1/admin/keys | python3 -m json.tool
# Find their key_id, then:
curl -s -X DELETE -H "Authorization: Bearer $HEXR_ADMIN_KEY" \
  https://api.hexr.cloud/v1/admin/keys/{key_id}
```

### Delete a Volunteer's Namespace (nuclear option)

```bash
kubectl delete namespace tenant-{name}
```

### Adjust Credits

```bash
curl -s -X POST \
  -H "Authorization: Bearer $HEXR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": 50, "reason": "bonus credits for feedback"}' \
  https://api.hexr.cloud/v1/tenants/{tenant_id}/credits
```

---

## 6. Pre-Volunteer Checklist

Before the volunteer day, verify:

- [ ] Invite code created and tested (`HEXR-VOLUNTEER-2026`)
- [ ] GKE cluster has capacity (`kubectl top nodes`)
- [ ] Cloud API is healthy (`curl https://api.hexr.cloud/healthz`)
- [ ] Dashboard is accessible (`https://app.hexr.cloud` — if deployed)
- [ ] Private PyPI is serving SDK (`pip install hexr-sdk --index-url https://pypi.hexr.cloud/simple/`)
- [ ] Example repo pushed to GitHub (`https://github.com/hexrdev/examples`)
- [ ] All 3 reference agents running 4/4 in `tenant-hexr-internal`
