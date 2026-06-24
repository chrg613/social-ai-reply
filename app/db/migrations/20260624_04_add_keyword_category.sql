-- Add category column to discovery_keywords
-- Required for the categorized keyword system (pain_point, solution_seeking,
-- competitor_alternative, general_buyer_seller, user_intent)
ALTER TABLE discovery_keywords
ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'general_buyer_seller';
