import { isValidObjectId } from 'mongoose';
import { Users } from '../../user_management/schema/users.schema';

/** Resolve the current owner on every token request, never from cached claims. */
export async function isShareOwnerActive(ownerId: string, orgId: string): Promise<boolean> {
  if (!isValidObjectId(ownerId) || !isValidObjectId(orgId)) return false;
  const owner = await Users.findOne({
    _id: ownerId,
    orgId,
    isDeleted: { $ne: true },
    isDisabled: { $ne: true },
    kind: { $ne: 'service' },
  }).select('_id').lean().exec();
  return owner !== null;
}
