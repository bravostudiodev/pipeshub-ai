import { NextFunction, Response } from 'express';
import mongoose from 'mongoose';
import { AuthenticatedServiceRequest } from '../../../libs/middlewares/types';
import { ChatSession } from '../schema/chat.session.schema';
import { ChatSessionMessage } from '../schema/chat.session.message.schema';

/** Service-only membership check. Deliberately limited to the caller's own
 * sessions; shared/project access is not inferred from request-supplied data. */
export const imageAttachmentMembership = async (
  req: AuthenticatedServiceRequest,
  res: Response,
  next: NextFunction,
): Promise<void> => {
  try {
    const { orgId, userId } = req.tokenPayload ?? {};
    const { conversationId, virtualRecordId } = req.body ?? {};
    if (
      typeof orgId !== 'string' || !mongoose.isValidObjectId(orgId) ||
      typeof userId !== 'string' || !mongoose.isValidObjectId(userId) ||
      typeof conversationId !== 'string' || !mongoose.isValidObjectId(conversationId) ||
      typeof virtualRecordId !== 'string' || virtualRecordId.length < 1 || virtualRecordId.length > 128
    ) {
      res.status(400).json({ allowed: false });
      return;
    }
    const session = await ChatSession.exists({ _id: conversationId, orgId, userId, isDeleted: { $ne: true } });
    if (!session) {
      res.json({ allowed: false });
      return;
    }
    const message = await ChatSessionMessage.exists({
      sessionId: conversationId,
      messageType: 'user_query',
      attachments: { $elemMatch: { virtualRecordId, mimeType: { $in: ['image/png', 'image/jpeg', 'image/jpg'] } } },
    });
    res.json({ allowed: Boolean(message) });
  } catch (error) {
    next(error);
  }
};
