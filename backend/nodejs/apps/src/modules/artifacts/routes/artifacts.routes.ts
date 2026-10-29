import { Router } from 'express';
import { Container } from 'inversify';
import { AuthMiddleware } from '../../../libs/middlewares/auth.middleware';
import { requireScopes } from '../../../libs/middlewares/require-scopes.middleware';
import { OAuthScopeNames } from '../../../libs/enums/oauth-scopes.enum';
import { ValidationMiddleware } from '../../../libs/middlewares/validation.middleware';
import { AppConfig } from '../../tokens_manager/config/config';
import {
  artifactIdParamsSchema,
  listArtifactsSchema,
  shareIdParamsSchema,
  createShareSchema,
} from '../validators/artifacts.validators';
import { createArtifactShare, listArtifactShares, revokeArtifactShare } from '../controllers/share-owner.controller';
import {
  getArtifact,
  listArtifactVersions,
  listArtifacts,
} from '../controllers/artifacts.controller';

export function createArtifactsRouter(container: Container): Router {
  const router = Router();
  const authMiddleware = container.get<AuthMiddleware>('AuthMiddleware');
  const appConfig = container.get<AppConfig>('AppConfig');

  router.get(
    '/',
    authMiddleware.authenticate,
    requireScopes(OAuthScopeNames.KB_READ, OAuthScopeNames.CONNECTOR_READ),
    ValidationMiddleware.validate(listArtifactsSchema),
    listArtifacts(appConfig),
  );

  router.post(
    '/:artifactId/shares',
    authMiddleware.authenticate,
    requireScopes(OAuthScopeNames.KB_READ, OAuthScopeNames.CONNECTOR_READ),
    ValidationMiddleware.validate(createShareSchema),
    createArtifactShare(appConfig),
  );
  router.get(
    '/:artifactId/shares',
    authMiddleware.authenticate,
    requireScopes(OAuthScopeNames.KB_READ, OAuthScopeNames.CONNECTOR_READ),
    ValidationMiddleware.validate(artifactIdParamsSchema),
    listArtifactShares(),
  );
  router.delete(
    '/:artifactId/shares/:shareId',
    authMiddleware.authenticate,
    requireScopes(OAuthScopeNames.KB_READ, OAuthScopeNames.CONNECTOR_READ),
    ValidationMiddleware.validate(shareIdParamsSchema),
    revokeArtifactShare(),
  );

  router.get(
    '/:artifactId/versions',
    authMiddleware.authenticate,
    requireScopes(OAuthScopeNames.KB_READ, OAuthScopeNames.CONNECTOR_READ),
    ValidationMiddleware.validate(artifactIdParamsSchema),
    listArtifactVersions(appConfig),
  );

  router.get(
    '/:artifactId',
    authMiddleware.authenticate,
    requireScopes(OAuthScopeNames.KB_READ, OAuthScopeNames.CONNECTOR_READ),
    ValidationMiddleware.validate(artifactIdParamsSchema),
    getArtifact(appConfig),
  );

  return router;
}
