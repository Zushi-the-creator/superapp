#!/bin/bash
# Deploy both services to production
echo "Deploying to production..."

# Deploy backend to Fly.io
echo ""
echo "==> Deploying backend to Fly.io..."
fly deploy

# Deploy frontend to Vercel
echo ""
echo "==> Deploying frontend to Vercel..."
cd frontend && vercel --prod
cd ..

echo ""
echo "Done! Production URLs:"
echo "  Frontend: https://superapp-trading.vercel.app"
echo "  Backend:  https://superapp-trading-api.fly.dev"
