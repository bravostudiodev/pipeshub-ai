import { Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
import { AuthenticatedUserRequest } from '../../../libs/middlewares/types';
import { Logger } from '../../../libs/services/logger.service';
import {
  InternalServerError,
  UnauthorizedError,
} from '../../../libs/errors/http.errors';
import { HttpMethod } from '../../../libs/enums/http-methods.enum';
import { AppConfig } from '../../tokens_manager/config/config';
import {
  executeConnectorCommand,
  handleBackendError,
} from '../../tokens_manager/utils/connector.utils';
import { ConversationTitleService } from '../services/conversation-title.service';
import { isDeckZip } from '../routes/deck-preview.routes';

const logger = Logger.getInstance({
  service: 'Artifacts Controller',
});

type ArtifactListItem = {
  conversationId?: string | null;
  conversationTitle?: string;
  [key: string]: unknown;
};

type ArtifactListResponse = {
  items?: ArtifactListItem[];
  pagination?: {
    page?: number;
    limit?: number;
    totalCount?: number;
    totalPages?: number;
  };
};

type ArtifactVersionsResponse = {
  versions?: unknown;
};

function requirePayload(
  data: unknown,
  message: string,
): Record<string, unknown> {
  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    throw new InternalServerError(message);
  }
  return data as Record<string, unknown>;
}

function artifactUri(
  connectorBackend: string,
  artifactId: string,
  suffix = '',
): string {
  return `${connectorBackend}/api/v1/artifacts/${encodeURIComponent(artifactId)}${suffix}`;
}

function buildQueryString(query: Record<string, unknown>): string {
  const params = new URLSearchParams();
  const mapping: Record<string, string> = {
    page: 'page',
    limit: 'limit',
    search: 'search',
    artifactTypes: 'artifact_types',
    conversationId: 'conversation_id',
    dateFrom: 'date_from',
    dateTo: 'date_to',
    sortBy: 'sort_by',
    sortOrder: 'sort_order',
  };
  for (const [from, to] of Object.entries(mapping)) {
    const value = query[from];
    if (value !== undefined && value !== null && String(value).length > 0) {
      params.set(to, String(value));
    }
  }
  return params.toString();
}

async function enrichConversationTitles(
  items: ArtifactListItem[],
  orgId: string,
  userId: string,
): Promise<ArtifactListItem[]> {
  const conversationIds = items
    .map((item) => item.conversationId)
    .filter((id): id is string => Boolean(id));
  if (!conversationIds.length) {
    return items;
  }
  const titles = await ConversationTitleService.batchTitles(
    conversationIds,
    orgId,
    userId,
  );
  return items.map((item) => {
    if (!item.conversationId) {
      return item;
    }
    const title = titles.get(item.conversationId);
    return title ? { ...item, conversationTitle: title } : item;
  });
}

function requireIdentity(req: AuthenticatedUserRequest): {
  userId: string;
  orgId: string;
} {
  const { userId, orgId } = req.user || {};
  if (!userId || !orgId) {
    throw new UnauthorizedError('User not authenticated');
  }
  return { userId: String(userId), orgId: String(orgId) };
}

export const listArtifacts =
  (appConfig: AppConfig) =>
  async (
    req: AuthenticatedUserRequest,
    res: Response,
    next: NextFunction,
  ): Promise<void> => {
    try {
      const { userId, orgId } = requireIdentity(req);
      const qs = buildQueryString(req.query as Record<string, unknown>);
      const uri = `${appConfig.connectorBackend}/api/v1/artifacts${qs ? `?${qs}` : ''}`;
      const connectorResponse =
        await executeConnectorCommand<ArtifactListResponse>(
          uri,
          HttpMethod.GET,
          req.headers as Record<string, string>,
        );
      const statusCode = connectorResponse.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw handleBackendError(connectorResponse, 'list artifacts');
      }
      const data = requirePayload(
        connectorResponse.data,
        'Failed to list artifacts',
      );
      const items = Array.isArray(data.items)
        ? (data.items as ArtifactListItem[])
        : [];
      data.items = await enrichConversationTitles(items, orgId, userId);
      res.status(statusCode).json(data);
    } catch (error: unknown) {
      logger.error('Error listing artifacts', { error });
      next(handleBackendError(error, 'list artifacts'));
    }
  };

export const getArtifact =
  (appConfig: AppConfig) =>
  async (
    req: AuthenticatedUserRequest,
    res: Response,
    next: NextFunction,
  ): Promise<void> => {
    try {
      const { userId, orgId } = requireIdentity(req);
      const { artifactId } = req.params as { artifactId: string };
      const connectorResponse = await executeConnectorCommand<ArtifactListItem>(
        artifactUri(appConfig.connectorBackend, artifactId),
        HttpMethod.GET,
        req.headers as Record<string, string>,
      );
      const statusCode = connectorResponse.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw handleBackendError(connectorResponse, 'get artifact');
      }
      const data = requirePayload(
        connectorResponse.data,
        'Failed to get artifact',
      ) as ArtifactListItem;
      const [enriched] = await enrichConversationTitles([data], orgId, userId);
      res.status(statusCode).json(enriched);
    } catch (error: unknown) {
      logger.error('Error getting artifact', { error });
      next(handleBackendError(error, 'get artifact'));
    }
  };

export const createDeckPreview =
  (appConfig: AppConfig) =>
  async (
    req: AuthenticatedUserRequest,
    res: Response,
    next: NextFunction,
  ): Promise<void> => {
    try {
      const { userId, orgId } = requireIdentity(req);
      const artifactId = req.params.artifactId;
      if (!artifactId) {
        res.status(404).json({ message: 'Presentation is unavailable.' });
        return;
      }
      const requestBody = req.body as { version?: unknown } | undefined;
      const version = requestBody?.version;
      if (
        typeof version !== 'number' ||
        !Number.isSafeInteger(version) ||
        version < 1 ||
        !appConfig.scopedJwtSecret
      ) {
        res.status(400).json({ message: 'Invalid presentation version.' });
        return;
      }
      const response = await executeConnectorCommand<Record<string, unknown>>(
        artifactUri(appConfig.connectorBackend, artifactId),
        HttpMethod.GET,
        req.headers as Record<string, string>,
      );
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw handleBackendError(response, 'get presentation artifact');
      }
      const detail = requirePayload(
        response.data,
        'Failed to load presentation artifact',
      );
      const versions = Array.isArray(detail.versions)
        ? (detail.versions as Array<{ version?: unknown }>)
        : [];
      const knownVersion =
        detail.version === version ||
        versions.some((item) => item.version === version);
      const mimeType = detail.mimeType;
      if (!isDeckZip(detail.name, mimeType) || typeof detail.name !== 'string' || !knownVersion) {
        res.status(404).json({ message: 'Presentation is unavailable.' });
        return;
      }
      const capability = jwt.sign(
        {
          purpose: 'deck-preview',
          artifactId,
          version,
          userId,
          orgId,
          name: detail.name,
          mimeType,
        },
        appConfig.scopedJwtSecret,
        { algorithm: 'HS256' },
      );
      // Validate the selected version's built archive before treating a ZIP as
      // a deck, so ordinary ZIP files retain their usual download-only view.
      const serviceToken = jwt.sign(
        { orgId, userId, artifactId, version, name: detail.name, mimeType, scopes: ['artifact-deck:content'] },
        appConfig.scopedJwtSecret,
        { algorithm: 'HS256', expiresIn: '60s' },
      );
      const probeUrl = new URL('/api/v1/internal/artifact-deck/file', appConfig.connectorBackend);
      probeUrl.searchParams.set('path', 'index.html');
      const probe = await fetch(probeUrl, { headers: { Authorization: `Bearer ${serviceToken}` }, redirect: 'error', signal: AbortSignal.timeout(120_000) });
      await probe.body?.cancel().catch(() => undefined);
      if (!probe.ok) {
        res.status(404).json({ message: 'Presentation is unavailable.' });
        return;
      }
      res.set({
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
      });
      res.json({
        previewUrl: `/decks/${encodeURIComponent(artifactId)}/${version}/${capability}/index.html`,
      });
    } catch (error: unknown) {
      next(handleBackendError(error, 'create presentation preview'));
    }
  };

export const listArtifactVersions =
  (appConfig: AppConfig) =>
  async (
    req: AuthenticatedUserRequest,
    res: Response,
    next: NextFunction,
  ): Promise<void> => {
    try {
      requireIdentity(req);
      const { artifactId } = req.params as { artifactId: string };
      const connectorResponse =
        await executeConnectorCommand<ArtifactVersionsResponse>(
          artifactUri(appConfig.connectorBackend, artifactId, '/versions'),
          HttpMethod.GET,
          req.headers as Record<string, string>,
        );
      const statusCode = connectorResponse.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw handleBackendError(connectorResponse, 'list artifact versions');
      }
      const data = requirePayload(
        connectorResponse.data,
        'Failed to list artifact versions',
      );
      res.status(statusCode).json(data);
    } catch (error: unknown) {
      logger.error('Error listing artifact versions', { error });
      next(handleBackendError(error, 'list artifact versions'));
    }
  };
