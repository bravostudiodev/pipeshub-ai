import mongoose, { Document, Model, Schema } from 'mongoose';

/** A share is an authority to serve one version, not a copy of its content. */
export interface ArtifactShare extends Document {
  tokenHash: string;
  artifactId: string;
  version: number;
  contentHash: string;
  name: string;
  mimeType: string;
  orgId: string;
  ownerId: string;
  createdAt: Date;
  expiresAt: Date;
  revokedAt: Date | null;
}

const artifactShareSchema = new Schema<ArtifactShare>(
  {
    tokenHash: { type: String, required: true, match: /^[0-9a-f]{64}$/, select: false },
    artifactId: { type: String, required: true },
    version: { type: Number, required: true, min: 1, validate: Number.isSafeInteger },
    contentHash: { type: String, required: true, match: /^[0-9a-f]{64}$/ },
    name: { type: String, required: true, maxlength: 255 },
    mimeType: { type: String, required: true, maxlength: 255 },
    orgId: { type: String, required: true },
    ownerId: { type: String, required: true },
    createdAt: { type: Date, required: true, default: Date.now, immutable: true },
    expiresAt: { type: Date, required: true },
    revokedAt: { type: Date, default: null },
  },
  { versionKey: false, strict: 'throw' },
);

artifactShareSchema.index({ tokenHash: 1 }, { unique: true });
artifactShareSchema.index({ orgId: 1, ownerId: 1, artifactId: 1, expiresAt: 1 });
// TTL cleanup is asynchronous. Every read must independently check expiresAt.
artifactShareSchema.index({ expiresAt: 1 }, { expireAfterSeconds: 0 });

export const ArtifactShareModel: Model<ArtifactShare> =
  (mongoose.models.artifactShare as Model<ArtifactShare> | undefined) ||
  mongoose.model<ArtifactShare>('artifactShare', artifactShareSchema);
