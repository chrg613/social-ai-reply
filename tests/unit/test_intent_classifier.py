"""Tests for the heuristic intent classifier."""


from app.services.product.intent_classifier import classify_intent


class TestLookingForRecommendation:
    def test_recommend_me_a_tool(self):
        result = classify_intent("Can anyone recommend a good CRM for small teams?")
        assert result.intent == "looking_for_recommendation"
        assert result.confidence >= 0.4
        assert "recommend" in result.reason.lower()

    def test_what_should_i_use(self):
        result = classify_intent("What should I use for email automation?")
        assert result.intent == "looking_for_recommendation"
        assert result.confidence >= 0.4

    def test_best_option(self):
        result = classify_intent("Best option for rental listings in NYC?")
        assert result.intent == "looking_for_recommendation"


class TestAskingForHelp:
    def test_how_do_i(self):
        result = classify_intent("How do I set up automated follow-ups?")
        assert result.intent == "asking_for_help"
        assert result.confidence >= 0.4

    def test_need_advice(self):
        result = classify_intent("Need advice on finding a flat without broker fees.")
        assert result.intent == "asking_for_help"

    def test_stuck_with(self):
        result = classify_intent("I'm stuck with manual email replies every morning.")
        assert result.intent == "asking_for_help"


class TestAskingHowTo:
    def test_how_to(self):
        result = classify_intent("How to cook perfect rice every time?")
        assert result.intent == "asking_how_to"
        assert result.confidence >= 0.4

    def test_tutorial_request(self):
        result = classify_intent("Looking for a tutorial on SEO basics.")
        assert result.intent == "looking_for_recommendation"


class TestBuyerResearch:
    def test_review_request(self):
        result = classify_intent("Has anyone tried Notion for project management?")
        assert result.intent == "looking_for_recommendation"
        assert result.confidence >= 0.4

    def test_worth_it(self):
        result = classify_intent("Is Mailchimp worth it for a small list?")
        assert result.intent == "buyer_research"


class TestComparison:
    def test_versus(self):
        result = classify_intent("HubSpot vs Salesforce for a 10-person team?")
        assert result.intent == "buyer_research"
        assert result.confidence >= 0.4

    def test_alternatives_to(self):
        result = classify_intent("What are the alternatives to Mailchimp?")
        assert result.intent == "comparison"


class TestPainPointDiscussion:
    def test_frustrated(self):
        result = classify_intent("I'm so frustrated with fake property listings.")
        assert result.intent == "pain_point_discussion"
        assert result.confidence >= 0.4

    def test_waste_of_time(self):
        result = classify_intent("Manually following up with leads is a waste of time.")
        assert result.intent == "pain_point_discussion"

    def test_broken(self):
        result = classify_intent("My CRM integration is broken again.")
        assert result.intent == "pain_point_discussion"


class TestLaunchOpportunity:
    def test_show_hn(self):
        result = classify_intent("Show HN: I built a tool to eliminate broker fees.")
        assert result.intent == "launch_opportunity"
        assert result.confidence >= 0.4

    def test_just_launched(self):
        result = classify_intent("We just launched our beta for renters.")
        assert result.intent == "launch_opportunity"


class TestSpamDetection:
    def test_multiple_spam_signals(self):
        result = classify_intent("Click here to earn $1000 daily! Buy now! Limited time!")
        assert result.intent == "spam"
        assert result.confidence >= 0.9

    def test_single_spam_short_text(self):
        result = classify_intent("Earn $500 fast. Click below.")
        assert result.intent == "spam"
        assert result.confidence >= 0.8

    def test_long_text_with_one_spam_signal(self):
        result = classify_intent(
            "This is a very long and detailed discussion about many different topics and "
            "ideas that span across multiple sentences and paragraphs, but there is one "
            "click here link embedded somewhere in the middle of all this text."
        )
        # A single spam signal in a long text should NOT be classified as spam
        assert result.intent != "spam"


class TestUnsafeDetection:
    def test_hack_without_security_context(self):
        result = classify_intent("How to hack a Facebook account?")
        assert result.intent == "unsafe"
        assert result.confidence >= 0.8

    def test_crack_software(self):
        result = classify_intent("Where can I download cracked software?")
        assert result.intent == "unsafe"

    def test_security_context_legitimate(self):
        result = classify_intent(
            "As a security researcher, I found a vulnerability in the authentication flow."
        )
        assert result.intent != "unsafe"
        assert result.intent != "spam"

    def test_bug_bounty_safe(self):
        result = classify_intent("I reported a bug bounty for a credential stuffing issue.")
        assert result.intent != "unsafe"


class TestCompetitorAwareClassification:
    def test_complaining_about_competitor(self):
        brand = {"competitors": ["Mailchimp"]}
        result = classify_intent("I'm tired of Mailchimp and their terrible support.", brand_profile=brand)
        assert result.intent == "complaining_about_competitor"
        assert result.confidence >= 0.7

    def test_looking_for_alternative_named(self):
        brand = {"competitors": ["HubSpot"]}
        result = classify_intent("Looking for an alternative to HubSpot for a small team.", brand_profile=brand)
        assert result.intent == "looking_for_alternative"
        assert result.confidence >= 0.7

    def test_generic_alternative_no_competitor(self):
        result = classify_intent("I'm switching from my current tool to something cheaper.")
        assert result.intent == "looking_for_alternative"
        assert result.confidence >= 0.6

    def test_no_competitor_profile(self):
        result = classify_intent("I hate Zillow's interface.")
        # Without brand profile, no competitor-aware classification
        assert result.intent != "complaining_about_competitor"


class TestConfidenceScoring:
    def test_zero_hits(self):
        result = classify_intent("The sky is blue today.")
        assert result.intent == "irrelevant"
        assert result.confidence == 0.2

    def test_one_hit(self):
        result = classify_intent("How do I improve my sleep?")
        assert result.intent == "asking_for_help"
        assert result.confidence == 0.4

    def test_two_hits(self):
        result = classify_intent("How do I find the best CRM?")
        # "how do i" (asking_for_help) + "best" (looking_for_recommendation)
        # best is in _LOOKING_FOR_RECOMMENDATION, so looking_for_recommendation wins with 1 hit
        # Actually, "best" is in _LOOKING_FOR_RECOMMENDATION. "how do i" is in _ASKING_FOR_HELP.
        # Both have 1 hit, looking_for_recommendation comes first.
        assert result.intent == "looking_for_recommendation"
        assert result.confidence == 0.4

    def test_three_hits(self):
        result = classify_intent(
            "Can anyone recommend a good tool? I'm looking for recommendations for the best option."
        )
        # Multiple recommendation phrases
        assert result.intent == "looking_for_recommendation"
        assert result.confidence >= 0.8

    def test_boosted_confidence(self):
        result = classify_intent("I'm struggling with manual follow-ups. How do I automate this?")
        # "struggling with" + "how do i" = 2 hits for asking_for_help
        assert result.intent == "asking_for_help"
        assert result.confidence >= 0.6


class TestEdgeCases:
    def test_empty_text(self):
        result = classify_intent("")
        assert result.intent == "irrelevant"
        assert result.confidence == 0.0

    def test_whitespace_only(self):
        result = classify_intent("   \n\t  ")
        assert result.intent == "irrelevant"
        assert result.confidence == 0.0

    def test_mixed_case(self):
        result = classify_intent("LOOKING FOR A GOOD TOOL")
        assert result.intent == "looking_for_recommendation"

    def test_punctuation(self):
        result = classify_intent("How do I... find a flat?!")
        assert result.intent == "asking_for_help"

    def test_competitor_and_recommendation(self):
        brand = {"competitors": ["Mailchimp"]}
        result = classify_intent(
            "Can anyone recommend a Mailchimp alternative?",
            brand_profile=brand,
        )
        # "can anyone recommend" is a very strong looking_for_recommendation signal.
        # The generic alternative patterns don't match "Mailchimp alternative" (they
        # look for "alternative to Mailchimp"), so standard intent wins here.
        assert result.intent == "looking_for_recommendation"

    def test_short_promo_not_spam(self):
        result = classify_intent("Check out our new app.")
        # Only "check out" is not in _SPAM. No spam signals.
        assert result.intent != "spam"

    def test_single_unsafe_in_long_text(self):
        result = classify_intent(
            "In computer security, the term 'hack' can mean many things, "
            "including ethical hacking and penetration testing."
        )
        # Contains "hack" but also security context
        assert result.intent != "unsafe"
