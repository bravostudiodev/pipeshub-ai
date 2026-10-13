// Import this first in every process entry point: it loads .env and installs the outbound
// proxy hooks before any other application module (and the HTTP clients they build) loads.
import 'dotenv/config';
import { installOutboundHttp } from './libs/utils/outbound-http';

installOutboundHttp();
