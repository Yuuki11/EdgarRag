# Kubernetes Autoscaling And Load Testing

FinEdgar includes an autoscaling profile for local HPA demonstrations.

Deploy it with:

```bash
scripts/k8s/deploy.sh autoscaling
```

Run the in-cluster k6 load test:

```bash
scripts/k8s/load-test.sh
```

Watch scaling:

```bash
kubectl get hpa -n finedgar -w
kubectl get pods -n finedgar -w
```

## What Scales

The HPA scales the `web-api` Deployment using CPU utilization. The default range
is:

```text
minReplicas: 2
maxReplicas: 4
targetCPUUtilizationPercentage: 65
```

The Kubernetes Service load-balances traffic across the API pods.

## What Does Not Scale Yet

Ollama remains a single StatefulSet replica in the base deployment. This means
chat requests can bottleneck on model inference even if the API Deployment
scales successfully.

This is intentional for the learning path. It demonstrates the difference
between scaling an HTTP layer and scaling the expensive model-serving layer.

## k6 Scenario

The included k6 test exercises:

- `/healthz`
- `/api/companies`

These endpoints are enough to demonstrate API load balancing and HPA behavior
without needing auth setup. Authenticated chat load testing can be added later
after a test-user provisioning path exists.

The in-cluster k6 Job sends traffic to the Traefik service and sets
`Host: finedgar.localhost`, so it validates the same Gateway route used by the
browser.

## Acceptance Checks

Use these checks during demos:

```bash
kubectl get hpa -n finedgar
kubectl describe hpa -n finedgar finedgar-finedgar-web
kubectl top pods -n finedgar
kubectl logs -n finedgar job/finedgar-k6
```

Expected result:

- k6 generates sustained traffic
- HPA observes API CPU utilization
- the API Deployment increases replicas when threshold is exceeded
- the Service continues routing traffic while replicas change
