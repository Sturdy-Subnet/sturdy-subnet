#!/bin/bash

# Initialize the database if it doesn't exist
dbmate --url "sqlite:/app/validator_database.db" up

# Create logs directory if it doesn't exist
mkdir -p /app/logs

# Construct wandb flag based on environment variable
WANDB_FLAG=""
if [ "${WANDB_OFF}" = "true" ]; then
    WANDB_FLAG="--wandb.off"
fi

# Start the validator with PM2 and set logging files
pm2 start --name validator \
    --output /app/logs/validator.out.log \
    --error /app/logs/validator.error.log \
    --interpreter=python3 \
    neurons/validator.py -- \
    --netuid ${NETUID:-10} \
    --subtensor.network ${NETWORK:-wss://entrypoint-finney.opentensor.ai:443} \
    --wallet.name ${WALLET_NAME:-default} \
    --wallet.hotkey ${WALLET_HOTKEY:-default} \
    --logging.debug \
    --axon.port ${AXON_PORT:-8001} \
    --api_port ${API_PORT:-8000} \
    ${WANDB_FLAG}

# Keep the container running and follow logs
pm2 logs